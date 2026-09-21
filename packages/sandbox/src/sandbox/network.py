"""Feature 158's law: egress is rejected at the namespace level, not by rule.

app_spec.xml, "Untrusted Code Sandbox", feature 158: *System places the sandbox
in a network namespace with no interfaces, which rejects egress at the namespace
level rather than by firewall rule.*  docs/nullius-tech-architecture.md §5.2
gives the control its own row — ``Network | Namespace with no interfaces. Not a
firewall rule.`` — and §3's zone map states the posture the row serves in one
line: *"Z1 — Mutated by the loop | Signal code, exploration policy code | LLM
agents | Sandboxed: no network, no FS, seccomp, cgroup limits"*.  The sentence
decomposes into four claims, each owned here as a seam rather than a comment:

* **places the sandbox in a network namespace** — the subject, and the half of
  this feature that is a *mechanism* rather than a gate.  The member's other
  laws answer a future: features 157's, 164's, 165's and 167's subjects are
  offered *before* anything executes, and their verbs return explanations rather
  than acting.  A namespace is not a statement about a run — it is a thing a
  runtime *creates* and puts the box inside, so the object this law produces is
  a **placement**: :class:`NetworkNamespace`, the namespace a box runs in and
  the interfaces it holds, plus the specification a launcher hands its runtime
  (:meth:`NetworkNamespace.specification`, whose one key is the runtime's own
  spelling of "no network").  Nothing here creates a namespace: a Python object
  graph cannot call ``unshare`` or write a container config, and the division is
  the one feature 157 states between its isolation policy and the ``runsc``
  runtime that enforces it.

* **with no interfaces** — the configuration term, and the only part of a
  namespace an egress attempt can be judged against.  The namespace arrives from
  the caller as the interfaces it holds (:attr:`NetworkNamespace.interfaces`),
  and the load-bearing read is :meth:`NetworkNamespace.egress_interfaces` — the
  ones that could carry a packet *off the box*.  An empty egress surface is the
  mechanism: §5.2's row is not a rule that was written and denies, it is the
  absence of any path a rule would have had to deny.

* **which rejects egress at the namespace level** — the consequent, and the
  gate.  One dial-out by code inside the box is presented as an
  :class:`EgressPath` and answered by :func:`reject_egress` with a
  :class:`NetworkDecision` whose reason names what the namespace held.  The
  rejection **answers** rather than raises — §6.1's pipeline runs unattended
  over thousands of candidates and *"this one tried to dial out"* must reach an
  operator as a fact about a run rather than as a crashed evaluator — and
  :meth:`NetworkDecision.require` is where a launcher takes it as
  :class:`~sandbox.errors.EgressRejected`.

* **rather than by firewall rule** — the contrast clause, and the reason this
  feature is not a second copy of feature 149.  §17's *"Z1 sandboxes: egress
  denied by default"* is the **policy**, owned by
  :mod:`infra.security.sandbox_egress`, and its refusals are about *rules*: a
  document that grants an allowance, an attempt that reaches the data lake, an
  origin the policy does not list.  This law is the **mechanism** that policy
  names as the enforcement — feature 149's own docstring says so (*"at runtime
  the sandbox runs in a network namespace with no interfaces, so egress is
  rejected at the namespace level rather than by firewall rule (§2's 'Sandboxed:
  no network'; feature 158's plugin)"*).  So every reason here is about an
  **interface**, never about a rule, and
  :attr:`NetworkDecision.at_namespace` is the clause as a value: it is ``True``
  exactly when the rejection was the namespace's own doing, and ``False`` for
  every refusal that came from somewhere further up the stack.  An operator
  reading ``at-namespace`` knows the box could not have crossed; one reading a
  refusal with it ``False`` knows the box was not placed as §5.2 requires and
  something *else* is holding the line — which is the finding this clause exists
  to make visible.

**Why the loopback interface is not an interface, and the honesty of saying
so.**  A real network namespace always holds ``lo`` — it is created with the
namespace and it cannot be removed.  §5.2's row says *no interfaces*, and read
literally that would refuse every namespace a kernel can actually build, which
would make the law unfalsifiable rather than strict.  So the law counts
**egress-capable** interfaces (:meth:`NetworkNamespace.egress_interfaces`) and
:data:`LOOPBACK_NAMES` is the exception, stated as data with its reason: a
packet sent to ``lo`` never leaves the box, so a namespace whose only interface
is loopback has no path to anything outside it.  That is also why the runtime
specification is ``NetworkMode: "none"`` (:data:`NO_NETWORK_MODE`) — the
container spelling of this row — rather than an empty interface list, because
the runtime's ``none`` mode is *precisely* "a namespace with loopback and
nothing else".  Writing ``lo`` off by name rather than comparing against a
deny-list of known-bad names is the conservative direction: an interface this
law has never heard of (``veth``, ``tun0``, a deployment's bridge) is
egress-capable until proven otherwise.

**The refusal is raised at the placement and returned at the gate.**  Two
audiences, two shapes, one law — the split feature 157's and feature 159's
modules draw.  A *placement* is built by trusted host code from what a runtime
reports, so a caller asking for the runtime specification of a box that cannot
be placed with no interfaces gets an exception it cannot ignore
(:class:`~sandbox.errors.NamespacePlacementError`); refusing there is the point,
because handing a runtime the spec for a namespace the box is not actually in
would be a deployment believing it applied §5.2's row.  An *egress attempt* is
made by untrusted code inside the box and arrives in every shape, well-formed
and hostile alike, so the gate *answers* attempts — a decision for every one,
raised for none, the same stance :func:`infra.security.sandbox_egress.
authorize_egress` takes for its own.

**The decision is computed, never assumed, and one of its spellings is an audit
finding.**  :func:`reject_egress` consults the placement's egress surface — a
real ``any``-shaped question over the compiled interface tuple, exactly the
consultation :meth:`infra.security.sandbox_egress.SandboxEgress.admits` makes
over its allowances — and admits the attempt only when the surface is non-empty,
which no box placed as §5.2 requires can produce.  So
:attr:`NetworkReason.BY_INTERFACE` is the unreachable acceptance: reading it is
proof the placement the gate consulted was not §5.2's namespace, and that the
box has a path out.  The three refusals are ordered so the *configuration* is
settled before the attempt's own path — the box's placement is the more
actionable fact, and both refuse the attempt either way.

**It compiles no committed artifact**, joining the builders that can say so —
the transfer's, the seed's, the fail-class law's, the quarantine's and feature
159's payload law.  Features 157, 167, 164, 163, 162 and 160 ship one because
each subject is a *setting* a deployment writes down — which isolation a box
declares, which imports it may reach, where its caps are pinned, where its
budget kills it, how large its cgroup is, which syscalls it may call.  This
law's subject is the box's *structure*, in the same sense and for the same
reason feature 159's is: §5.2 fixes "a namespace with no interfaces" for every
box in this deployment, and there is nothing a deployment could set differently
without leaving the architecture.  A ``network_policy.json`` here would be a
knob nobody turns — the objection :func:`sandbox.transfer.sandbox_transfer`'s
builder states for its own absent file, and the reason
:data:`infra.security.sandbox_egress.COMMITTED_SANDBOX_EGRESS_POLICY` is where
a deployment's *written* egress posture lives rather than here.  A non-``None``
component at this seat proves only that the law is loaded.

**Honest limits.**  This module is the law about the namespace, not the
namespace: it never calls ``unshare`` or ``clone``, never opens
``/sys/class/net``, never spawns a process and cannot see a packet a kernel
already dropped.  The enforcement is the runtime's — ``runsc`` creating the box
in a namespace with no interfaces (§18's stack choice) — and what holds is that
an attempt cannot be rejected without naming which interface could have carried
it, that the answer is derived from the namespace the caller handed rather than
from a hardcoded denial, and that *what this box's network posture is* is a
value a caller can read (:meth:`NetworkNamespace.egress_interfaces`,
:meth:`SandboxNetwork.isolated`).  A ``NetworkNamespace`` can be assembled by
hand holding an interface — exactly as a rogue egress allowance can — and the
gate's answer on one is itself the audit finding, which is the whole value of
``by-interface`` being a reachable spelling.  Below this law and above it sit
the two mechanisms that would matter if it were ever bypassed: feature 160's
seccomp ceiling denies the ``socket``/``connect`` family outright, and §1 P1's
data lake has no address this box could reach even with a route.  Enforce with
network policy, never with prompt instructions (§2): *"a prompt is not a
security boundary"*, and this module is the mechanism the policy is written
against.

Stdlib-only, like the rest of the member: ``enum`` and a pair of frozen tuples,
and no socket, namespace, container runtime or probe anywhere.  The module is
the law and the committed egress posture an operator applies is feature 149's.
"""

from __future__ import annotations

import enum
from collections.abc import Iterable
from typing import Any, Final

from .errors import (
    EgressRejected,
    NamespacePlacementError,
)

__all__ = [
    "EGRESS_REJECTED_CODE",
    "LOOPBACK_NAMES",
    "NAMESPACE_REQUIRED_CODE",
    "NETWORK_COMPONENT_NAME",
    "NO_NETWORK_MODE",
    "EgressPath",
    "NetworkDecision",
    "NetworkNamespace",
    "NetworkReason",
    "SandboxNetwork",
    "isolated_namespace",
    "reject_egress",
    "sandbox_network",
]

#: The component name this law registers under — beside feature 157's
#: ``sandbox``, feature 167's ``sandbox-imports``, feature 166's
#: ``sandbox-transfer``, feature 165's ``sandbox-seed``, feature 164's
#: ``sandbox-threads``, feature 163's ``sandbox-timeout``, feature 168's
#: ``sandbox-failclass``, feature 162's ``sandbox-budget``, feature 160's
#: ``sandbox-syscalls``, feature 161's ``sandbox-quarantine`` and feature 159's
#: ``sandbox-payload``, not instead of any of them: the factory's registry is
#: keyed by name and a later registration of the same name *replaces* the
#: earlier one, so a member carrying twelve controls carries twelve components,
#: each answering its own feature's question.
#:
#: Note what this name is *not*: ``sandbox-namespace`` would name the mechanism
#: rather than the law, and this member names its components after their
#: subject — the isolation, the imports, the transfer, the seed, the threads,
#: the timeout, the fail class, the budget, the syscalls, the quarantine, the
#: payload.  The subject here is the network.  Nor is it ``sandbox-egress``:
#: feature 149's law owns that word for the *policy* that denies egress by
#: default, and this law is the mechanism underneath it — one spelling each, so
#: a caller reading either name knows which of the two it is holding.
NETWORK_COMPONENT_NAME: Final[str] = "sandbox-network"

#: The greppable code every egress refusal carries — feature 158's own subject
#: written as a token, the discipline
#: :data:`sandbox.isolation.ISOLATION_REQUIRED_CODE`
#: (``gvisor_isolation_required``), :data:`sandbox.imports.DISALLOWED_IMPORT_CODE`
#: (``disallowed_import``), :data:`sandbox.syscalls.DISALLOWED_SYSCALL_CODE`
#: (``disallowed_syscall``) and :data:`sandbox.payload.PAYLOAD_CHANNEL_CODE`
#: (``payload_channel_required``) apply to theirs.  An operator grepping a log
#: for the rejection finds it by the feature's own words.
EGRESS_REJECTED_CODE: Final[str] = "egress_rejected"

#: The greppable code the *other* half of this law carries: a box could not be
#: placed in a network namespace with no interfaces, so there is no §5.2
#: placement to hand a runtime.  Two codes rather than one because the repairs
#: are on opposite sides of the seam — this one means a *placement* is wrong
#: (built by trusted host code, repaired by fixing the runtime configuration),
#: the other means an *attempt* was refused (made by untrusted code, repaired by
#: nothing, it is the box working) — the split feature 162's and feature 160's
#: two codes each make for their own laws.
NAMESPACE_REQUIRED_CODE: Final[str] = "network_namespace_required"

#: The runtime's own spelling of §5.2's row, and the one key
#: :meth:`NetworkNamespace.specification` hands a launcher.  ``none`` is the
#: container network mode that creates a namespace with **no interfaces but
#: loopback** — Docker's and the OCI runtime spec's word for exactly the
#: posture this feature's sentence names, which is why the specification is this
#: key rather than a list of interfaces: the runtime's vocabulary is not this
#: law's to rename, and a filter translated by each launcher would be a second
#: place for the two spellings to diverge (the division feature 160's
#: :meth:`~sandbox.syscalls.SyscallFilter.specification` draws for its own).
#:
#: That the runtime's ``none`` still creates ``lo`` is not a gap between the row
#: and the mechanism — it is the fact :data:`LOOPBACK_NAMES` exists to state,
#: and the reason this law counts *egress-capable* interfaces rather than
#: interfaces.
NO_NETWORK_MODE: Final[str] = "none"

#: The interfaces that cannot carry a packet off the box, in the two spellings a
#: deployment's runtime is likely to report.  A set rather than a single name
#: for the reason :data:`sandbox.syscalls.TERMINATION_SYSCALLS` accepts both
#: ``exit`` and ``exit_group``: Linux names loopback ``lo`` and the BSDs name it
#: ``lo0``, and a law that refused one of the two spellings would be a law about
#: a deployment's libc rather than about whether a packet can leave.
#:
#: **Why this set exists at all, since §5.2 says "no interfaces".**  A network
#: namespace is created *with* loopback; it cannot be removed, and a kernel that
#: refused to create one without it would leave this law with no namespace it
#: could ever admit.  So the row is read the way it is meant — the box has no
#: path to anything outside it — and the interfaces that could provide one are
#: what the law counts.  A packet sent to loopback never leaves the box, so a
#: namespace whose only interface is loopback has no egress surface, which is
#: the whole of the claim.
#:
#: Written as the *exception* rather than as a deny-list of known-bad names,
#: deliberately and in the conservative direction: an interface this law has
#: never heard of is egress-capable until it is proven otherwise, so a
#: deployment that adds ``veth``, ``tun0`` or a bridge of its own is caught by
#: default rather than by someone remembering to add it here.
LOOPBACK_NAMES: Final[frozenset[str]] = frozenset({"lo", "lo0"})


def _name_tuple(reported: object) -> tuple[str, ...]:
    """One reported interface list, normalised the one way this law reads it.

    **One normaliser, because two would be two answers to the same question.**
    :class:`NetworkNamespace` calls this in its constructor and
    :func:`_interfaces_of` calls it on whatever a duck-typed placement reports,
    so a caller's ``interfaces`` is read identically whether it arrived as a
    constructor argument or as an attribute — the one-provenance rule this
    member applies to every quantity it carries.

    A bare string is **one interface name**, not a sequence of characters.  The
    distinction is not pedantry: ``interfaces="eth0"`` is the natural way for a
    caller to say *the one interface I know about*, and iterating it would
    shatter the name into ``('e', 't', 'h', '0')`` — four interfaces the box
    never held, none of them loopback, and a refusal sentence naming nonsense.
    Reading it as the single name it plainly is also keeps the law's stated
    direction: an interface this law has never heard of is egress-capable until
    proven otherwise, and ``"eth0"`` read as one name is caught as egress.
    A string naming loopback (``"lo"``) is the one case where the single name is
    not egress-capable, and it is caught by the same filter as any other.

    Anything else that is not iterable reports no interfaces — the honest answer
    rather than a type error, and the conservative one: an absence of interfaces
    is §5.2's row, and it is the gate's *placement* check
    (:func:`_is_placement`) that refuses an object which is not a placement at
    all, so this read never has to be the thing that errors.
    """
    if isinstance(reported, str):
        return (reported,)
    if not isinstance(reported, Iterable):
        return ()
    return tuple(name for name in reported)


def _egress_names(names: Iterable[str]) -> tuple[str, ...]:
    """The subset of ``names`` that could carry a packet off the box, in order.

    The law's one filter, applied by both the class's
    :meth:`NetworkNamespace.egress_interfaces` and the duck-typed
    :func:`_egress_of`, so the two cannot disagree about whether a box has an
    egress surface — which is the whole of the claim this feature makes.
    """
    return tuple(
        name
        for name in names
        if not (isinstance(name, str) and name.strip().casefold() in LOOPBACK_NAMES)
    )


def _interfaces_of(namespace: object) -> tuple[str, ...]:
    """The interfaces a placement reports, in order, whoever built it.

    The read the whole law is computed from, taken duck-typed for the reason
    every other subject read in this member is: the loader imports the member
    under a scan alias, so a component the app composed holds a
    :class:`NetworkNamespace` from a *different* copy of this module, where
    ``isinstance`` cannot hold — the property
    :func:`sandbox.syscalls._subject_syscall` and
    :func:`sandbox.payload.authorize_payload_run` state for theirs.  A placement
    is the object that reports its interfaces, not the class that witnessed it,
    and a deployment's own placement type is read as happily as this one.

    A placement reporting no ``interfaces`` at all reports none — the honest
    answer rather than a type error, and the conservative direction: an absence
    of interfaces is §5.2's row, and the gate's *placement* check is what
    refuses an object that is not a placement.  Normalisation is
    :func:`_name_tuple`'s, so an attribute spelling read here and a constructor
    argument spelling read there cannot come out differently.
    """
    return _name_tuple(getattr(namespace, "interfaces", ()))


def _egress_of(namespace: object) -> tuple[str, ...]:
    """The egress surface of a placement: its interfaces minus loopback."""
    return _egress_names(_interfaces_of(namespace))


def _is_placement(namespace: object) -> bool:
    """Whether ``namespace`` is a thing this law can read as a placement.

    The contract is one read — *report the interfaces you were given* — so the
    test is the read itself rather than a class.  ``None`` is *not* a placement
    and is handled before this is reached: it is the state
    :attr:`NetworkReason.NOT_PLACED` describes, a refusal rather than a caller
    error.
    """
    return hasattr(namespace, "interfaces")


def _row_sentence() -> str:
    """§5.2's control-table row, verbatim, for every refusal to carry.

    One body rather than five literals, so each refusal names the *law it
    enforces* in the architecture's own words — ``Network | Namespace with no
    interfaces. Not a firewall rule.`` — and a reader of any one of them can
    find the row the others cite without grep.  The same one-body discipline
    :func:`sandbox.payload._row_sentence` and :func:`sandbox.seed._refusal` take
    for theirs.
    """
    return (
        "§5.2's control table gives the box its network posture in one row — "
        "'Network | Namespace with no interfaces. Not a firewall rule.' — and "
        "§3's zone map states what that row serves: 'Z1 — Mutated by the loop | "
        "Signal code, exploration policy code | LLM agents | Sandboxed: no "
        "network, no FS, seccomp, cgroup limits'"
    )


def _refusal(spelling: str, consequence: str) -> str:
    """The operator-facing sentence for an egress attempt the box refused.

    The one body every refusal composes: what the namespace held, which spelling
    of not-having-a-path that was, and what an attempt crossing would have cost.
    Every message begins with :data:`EGRESS_REJECTED_CODE` so an operator
    grepping a log finds the rejection by the feature's own words.
    """
    return (
        f"{EGRESS_REJECTED_CODE}: an egress attempt from a sandboxed box was "
        f"rejected because {spelling}. {consequence} {_row_sentence()}. The "
        f"rejection is this box's network namespace doing the refusing, not a "
        f"firewall rule above it (feature 158)."
    )


class NetworkReason(enum.StrEnum):
    """Why an attempt was admitted or rejected — the audit vocabulary.

    One enumeration carries the acceptance and the rejections, for the reason
    :class:`sandbox.isolation.RunReason`, :class:`sandbox.payload.PayloadReason`
    and :class:`infra.security.sandbox_egress.EgressReason` do: a decision's
    reason is one fact with two polarities and the audit line should read the
    same either way.  Every rejection here names an **interface** fact, never a
    rule — which is the feature's own contrast clause written as vocabulary, and
    what keeps this law's reasons tellable apart from feature 149's at a glance.
    """

    #: Rejected: the box's namespace holds no interface that could carry the
    #: attempt off it, so the attempt has no path out and the rejection is the
    #: namespace's own.  Feature 158's headline — §5.2's row firing — and the
    #: only reason :attr:`NetworkDecision.at_namespace` is ``True`` for.
    AT_NAMESPACE = "at-namespace"

    #: Rejected: the box was handed no namespace at all, so nothing places it
    #: and this law will not vouch for where it is.  A box in whatever namespace
    #: the host gave it has the host's network, and the refusal is the
    #: conservative answer rather than a claim that egress was impossible —
    #: :attr:`NetworkDecision.at_namespace` is ``False`` here precisely because
    #: the namespace did not do this refusing.
    NOT_PLACED = "not-placed"

    #: Rejected: the attempt's origin is not the box whose namespace was handed
    #: in.  An attempt attributed to another box is one this placement cannot
    #: speak about, and the answer is a refusal rather than a guess — the
    #: reading :attr:`infra.security.sandbox_egress.EgressReason.UNKNOWN_SANDBOX`
    #: gives an unlisted origin, for the same reason.
    UNKNOWN_SANDBOX = "unknown-sandbox"

    #: Admitted: the box's namespace holds an interface that could carry the
    #: attempt, so there is no namespace-level rejection to make.  No placement
    #: built the way §5.2 requires can produce this reason — the egress surface
    #: is empty by construction — so a decision reading ``by-interface`` is
    #: itself the audit finding: the placement it consulted was hand-built, and
    #: the box has a path out.  The exact role
    #: :attr:`infra.security.sandbox_egress.EgressReason.BY_ALLOWANCE` plays for
    #: feature 149, one mechanism down.
    BY_INTERFACE = "by-interface"


class NetworkNamespace:
    """The namespace one box runs in: the interfaces it holds, and nothing else.

    Feature 158's word is *places*, and this is the object "places" is carried
    by — a box and the network surface it was given, as a value the caller
    builds from what a runtime reported and hands the gate.  It is deliberately
    **not** a live namespace: nothing here has called ``unshare``, this object
    holds no file descriptor and no process, and :meth:`specification` only
    *describes* what a launcher should ask its runtime for.  That is the same
    division feature 157 draws between its isolation policy and the ``runsc``
    runtime, and feature 160 between its ceiling and the filter a runtime arms.

    **The consultation the gate makes is real.**  :meth:`egress_interfaces`
    derives the egress surface from :attr:`interfaces` on every call rather than
    caching a verdict, so the gate's answer is *the namespace arriving at its
    answer* — the stance :meth:`infra.security.sandbox_egress.SandboxEgress.
    admits` takes over its allowances.  Under every placement built the way
    §5.2 requires the tuple is empty and no attempt can be admitted; a placement
    built by hand with an interface in it is one the gate admits through, and
    :attr:`NetworkReason.BY_INTERFACE` on the decision is the finding.

    **``interfaces`` is what the runtime reported, in the runtime's spelling.**
    Named interfaces rather than a count, because the read side a deployment
    audits with is *which* interface a box holds: a box holding ``lo`` and a box
    holding ``eth0`` are both "one interface" and are opposite facts about
    whether untrusted code can reach the network.  The order is preserved, so
    two deployments' namespaces can be compared field by field — the property
    :class:`sandbox.budget.CgroupPolicy` and :class:`sandbox.syscalls.
    SyscallFilter` state for their own tuples.
    """

    __slots__ = ("component", "interfaces")

    def __init__(
        self,
        *,
        component: str = "",
        interfaces: Iterable[str] = (),
    ) -> None:
        self.component = component
        # Through the module's one normaliser, so a caller passing a single
        # interface name as a bare string is read as that one name rather than
        # as its characters — and so a namespace built here and one read
        # duck-typed by the gate cannot disagree about what it holds.
        self.interfaces: tuple[str, ...] = _name_tuple(interfaces)

    def egress_interfaces(self) -> tuple[str, ...]:
        """The interfaces that could carry a packet off this box, in order.

        The load-bearing read of the whole feature, and the one the gate
        consults: every reported interface except the loopback spellings of
        :data:`LOOPBACK_NAMES`, because a packet sent to loopback never leaves
        the box.  An empty tuple is §5.2's row holding — there is no interface a
        packet could leave by, which is a stronger statement than any rule that
        denies one.

        Derived per call rather than stored, so the emptiness is the *mechanism*
        and not a constant: a namespace handed an interface reports it here and
        the gate says so, which is what makes
        :attr:`NetworkReason.BY_INTERFACE` a reachable audit finding rather than
        a decoration.
        """
        return _egress_names(self.interfaces)

    @property
    def is_isolated(self) -> bool:
        """Whether this box is placed as §5.2 requires — no egress interface.

        Exposed as a boolean, because it is the difference between a box with no
        path out and a box with one, and a reader should not have to know that
        loopback does not count in order to ask.  ``True`` is the posture every
        box in this deployment is in; ``False`` means the namespace holds an
        interface and the box's egress is whatever the layer above it allows,
        which is the state the feature's contrast clause is about.
        """
        return not self.egress_interfaces()

    def holds(self, interface: object) -> bool:
        """Whether the namespace holds an interface by this name.

        A read, not a decision: the gate uses it to make its refusal's sentence
        say *which* interface the attempt named and whether the box ever had it,
        and the membership question it actually answers is
        :meth:`egress_interfaces`.  A name that is not a string holds nothing.
        """
        if not isinstance(interface, str):
            return False
        return interface in self.interfaces

    def specification(self) -> dict[str, Any]:
        """The namespace as the runtime configuration a launcher writes.

        Feature 158's word is *places*, and this is the verb that carries it:
        the caller hands the result to whatever spawns the box, and the runtime
        creates the namespace.  Nothing is created by calling it — the division
        feature 157 states between its isolation policy and the ``runsc`` runtime
        that enforces it.

        **It refuses for a namespace that is not isolated**, and that refusal is
        the point rather than an inconvenience: the specification this law would
        hand a runtime is §5.2's row, so producing one from a placement holding
        an interface would describe a box that is not the box being spawned —
        the deployment would believe it applied the row while the runtime built
        something else.  A caller reading the refusal has found a placement
        built by hand or reported wrong, and the repair is on the placement
        rather than here.  A fresh dict per call, never a shared one: the
        copy-then-hand discipline every other read side in this member applies,
        so a caller that mutated what it was handed cannot widen the namespace
        for the next one.
        """
        egress = self.egress_interfaces()
        if egress:
            raise NamespacePlacementError(
                f"{NAMESPACE_REQUIRED_CODE}: the namespace of box "
                f"{self.component!r} holds {len(egress)} interface(s) that "
                f"could carry a packet off it ({list(egress)!r}), so there is "
                f"no §5.2 placement to describe. {_row_sentence()}, and a "
                f"specification written from this placement would hand a "
                f"runtime the row while the box being spawned is in a namespace "
                f"that does not hold it — a deployment believing it applied the "
                f"posture this feature names. Refused rather than described "
                f"(feature 158)."
            )
        return {"NetworkMode": NO_NETWORK_MODE}

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return (
            f"NetworkNamespace(component={self.component!r}, "
            f"interfaces={list(self.interfaces)!r})"
        )


class EgressPath:
    """One dial-out from inside the box, as presented to the gate.

    Feature 158's sentence is about *egress* — a packet trying to leave — so the
    subject is one attempt rather than a whole run, the narrower unit
    :class:`sandbox.syscalls.SyscallAttempt` models for a call and
    :class:`infra.security.sandbox_egress.EgressAttempt` for feature 149's own
    gate.  Deliberately unvalidated beyond assignment: the gate models what
    untrusted code inside the box reached for, hostile shapes included, and
    *answers* them rather than refusing to parse them — the same stance feature
    149's attempt takes, and the reason a malformed destination produces a
    refusal rather than a parse error that would crash an unattended pipeline.

    **What it carries is what the runtime reported, never a probe.**  Nothing in
    this module opens a socket, reads ``/sys/class/net`` or watches a process:
    the runtime that owns the namespace is the one that knows an attempt was
    made and which interface would have carried it, so every field arrives as an
    argument — the same division that has feature 160's law read a *reported*
    syscall and feature 162's read a *reported* measurement.

    ``interface`` is the one field the law reads for its sentence rather than for
    its decision: a path inside a namespace with no egress interface names either
    nothing (there is no interface to leave by) or a name the box never held, and
    the refusal says which — the stance feature 160 takes toward the arguments a
    call carried.  ``destination``, ``port`` and ``protocol`` are carried for the
    refusal's sentence and for a ledger row, and no part of the answer depends on
    them.
    """

    __slots__ = ("destination", "interface", "origin", "port", "protocol")

    def __init__(
        self,
        *,
        origin: str = "",
        destination: Any = "",
        port: Any = 0,
        protocol: str = "tcp",
        interface: str = "",
    ) -> None:
        self.origin = origin
        self.destination = destination
        self.port = port
        self.protocol = protocol
        self.interface = interface

    def describe(self) -> str:
        """``api.exchange.com:443/tcp`` — the path as one reviewer-readable phrase.

        The operator line, and the reason the path is carried as a type rather
        than left implicit: a refusal's whole content is *where the box reached
        for* and *what the namespace held instead*, and a sentence naming only
        the second would read identically for an attempt at the data lake and one
        at a public host.
        """
        return f"{self.destination!r}:{self.port}/{self.protocol}"

    def row(self) -> dict[str, Any]:
        """The attempt as one store-shaped mapping.

        The shape a ledger row or an operator's incident note is written from:
        the origin, the path, and the interface it named.  Fresh dict per call,
        never a shared one — the copy-then-hand discipline
        :meth:`sandbox.syscalls.Commitment.row` and
        :meth:`sandbox.budget.BudgetBreach.row` apply to their own shapes.
        """
        row: dict[str, Any] = {
            "origin": self.origin,
            "destination": self.destination,
            "port": self.port,
            "protocol": self.protocol,
        }
        if self.interface:
            row["interface"] = self.interface
        return row

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return (
            f"EgressPath(origin={self.origin!r}, "
            f"destination={self.destination!r}, port={self.port}, "
            f"interface={self.interface!r})"
        )


class NetworkDecision:
    """The gate's whole answer: admitted or not, why, and in what words.

    ``admitted`` is the one field a caller must check, and it is *computed* from
    the placement's egress surface rather than set by a constant: under every
    namespace built the way §5.2 requires it is ``False``, so a box placed
    properly can never have an attempt admitted through it — the same
    "computed, never assumed" stance, and the same always-false polarity,
    :class:`infra.security.sandbox_egress.EgressDecision` takes for feature 149.

    :attr:`at_namespace` is this feature's own clause and the reason this class
    is not feature 149's decision reused: it says whether the rejection was the
    *namespace's* doing — :attr:`NetworkReason.AT_NAMESPACE`, and nothing else —
    so a caller can tell "the box could not have crossed" from "the box was not
    placed as §5.2 requires and something above it refused".  The second is not
    a weaker version of the first; it is a different operational fact with a
    different repair, which is why the feature's sentence bothers to say
    *rather than by firewall rule* at all.
    """

    __slots__ = ("admitted", "detail", "namespace", "path", "reason")

    def __init__(
        self,
        *,
        admitted: bool,
        reason: NetworkReason,
        detail: str,
        path: EgressPath | None = None,
        namespace: NetworkNamespace | None = None,
    ) -> None:
        self.admitted = admitted
        self.reason = reason
        self.detail = detail
        self.path = path
        self.namespace = namespace

    @property
    def rejected(self) -> bool:
        """Whether the box did not get to make this attempt — the headline.

        Every rejection reason and never the acceptance, so a caller that read a
        bare falsy as "the box was fine" cannot mistake an unplaced box for an
        admitted one — the distinction :attr:`sandbox.syscalls.SyscallDecision.
        rejected` and :attr:`sandbox.budget.BudgetDecision.refused` exist to
        keep for their own laws.
        """
        return not self.admitted

    @property
    def at_namespace(self) -> bool:
        """Whether the *namespace* rejected this attempt — the contrast clause.

        ``True`` exactly when the box's own namespace had no interface to carry
        the attempt, so the rejection needed no rule above it and none was
        consulted.  ``False`` for every other answer, including the other two
        refusals: an unplaced box and one that is not this namespace's own are
        both cases where something other than the namespace is holding the line,
        and an operator repairing them is looking at the runtime configuration
        rather than at the box's network posture.  Reading ``False`` on a
        refusal is the finding that this deployment is relying on feature 149's
        policy, or on a security group, for a rejection feature 158 exists to
        make structural.
        """
        return self.reason is NetworkReason.AT_NAMESPACE

    def require(self) -> None:
        """Raise :class:`~sandbox.errors.EgressRejected` unless admitted.

        The bridge between the gate's returned answer and the exception a
        launcher wants: a decision that admitted the attempt is a no-op, so a
        caller can use it unconditionally on the line after the box is placed.
        All three rejection reasons raise the one class, because the two halves
        of feature 158's sentence carry one error type and a caller never has to
        catch two — the division :meth:`sandbox.isolation.RunDecision.require`
        and :meth:`sandbox.payload.PayloadDecision.require` draw for their pairs.
        """
        if not self.admitted:
            raise EgressRejected(self.detail)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return (
            f"NetworkDecision(admitted={self.admitted}, "
            f"reason={self.reason!r}, at_namespace={self.at_namespace})"
        )


def _subject_path(subject: object) -> EgressPath:
    """``subject`` as an :class:`EgressPath`, tolerating a caller's own record.

    Reads an :class:`EgressPath` and any object carrying the same fields, so a
    deployment's own attempt type — or feature 149's
    :class:`infra.security.sandbox_egress.EgressAttempt`, which carries
    ``origin``, ``destination``, ``port`` and ``protocol`` under exactly these
    names — is answered without being re-described.  The tolerance is the one
    :func:`sandbox.syscalls._subject_syscall` and
    :func:`sandbox.budget._subject_measurement` extend to the shapes their own
    subjects arrive in, and for the same reason: the subject is the caller's
    object, not this module's.

    A field the subject does not carry arrives as the default rather than as an
    error, because an attempt is untrusted input and this law's job is to answer
    it — not to be the second thing that can go wrong with it.
    """
    if isinstance(subject, EgressPath):
        return subject
    return EgressPath(
        origin=getattr(subject, "origin", "") or "",
        destination=getattr(subject, "destination", "") or "",
        port=getattr(subject, "port", 0),
        protocol=getattr(subject, "protocol", "tcp") or "tcp",
        interface=getattr(subject, "interface", "") or "",
    )


def _subject_origin(subject: object) -> str:
    """The origin ``subject`` names, or ``""``.

    Read while building a sentence, so a subject carrying a non-string identity
    is reported as carrying none rather than crashing the refusal that was about
    to describe it — the courtesy :func:`sandbox.syscalls._subject_identity`
    extends to the attempts its own gate judges.
    """
    origin = getattr(subject, "origin", "")
    return origin if isinstance(origin, str) else ""


def _not_placed_refusal(path: EgressPath) -> str:
    """The refusal for a box handed no namespace at all."""
    return _refusal(
        f"nothing placed it: no network namespace was handed in for this box "
        f"(origin {path.origin!r}), so the box runs in whatever namespace the "
        f"host gave it",
        consequence=(
            "A box that was never placed has no namespace this law can consult, "
            "and a gate that read the absence as permission would be admitting "
            "egress on the strength of a placement nobody made — the host's "
            "own network is not §5.2's posture, and a launcher that spawned "
            "here would report an ordinary trial outcome for a candidate that "
            "could reach the world. Refused conservatively: hand the gate the "
            "namespace the box was placed in, or the box has not been placed "
            "(the runtime configuration is where the repair is)."
        ),
    )


def _unknown_sandbox_refusal(path: EgressPath, namespace: object) -> str:
    """The refusal for an attempt attributed to a box this namespace is not."""
    return _refusal(
        f"the namespace consulted belongs to box "
        f"{getattr(namespace, 'component', '')!r} and "
        f"the attempt names origin {path.origin!r}",
        consequence=(
            "One namespace answers for one box. An attempt attributed to "
            "another box is one this placement cannot speak about — its "
            "interfaces say nothing about the namespace the attempt was made "
            "in — and answering it either way would be reporting a decision "
            "made about a different box, which is worse than reporting none. "
            "Hand the gate the namespace of the box the attempt came from."
        ),
    )


def _at_namespace_refusal(
    path: EgressPath,
    namespace: object,
) -> str:
    """The refusal for the feature firing: there was no interface to leave by."""
    component = getattr(namespace, "component", "") or ""
    held = list(_interfaces_of(namespace))
    if path.interface:
        named = (
            f"the attempt names interface {path.interface!r}, which the "
            f"namespace of box {component!r} does not hold "
            f"(it holds {held!r})"
        )
    else:
        named = (
            f"the attempt names no interface to leave by, and the namespace of "
            f"box {component!r} holds none that could carry it "
            f"(its interfaces are {held!r}, and the "
            f"loopback spellings of {sorted(LOOPBACK_NAMES)!r} cannot carry a "
            f"packet off the box)"
        )
    return _refusal(
        named,
        consequence=(
            "There is no path out, so the packet is dropped where it was "
            "handed to the network stack: no route resolves, no neighbour is "
            "reachable and no rule was consulted — because a rule is not what "
            "refuses it. This is the feature's own clause working as stated "
            "(feature 158), and it is the stronger of the two mechanisms §17 "
            "names: a firewall rule that drifted open would let the attempt "
            "through, while a namespace with no interface has nothing to open "
            "(feature 149's policy is the other half, and this is what it is "
            "written against). The attempt is refused rather than retried: an "
            "untrusted signal that reaches for the network is a candidate whose "
            "result §1 P1 says cannot be trusted, and the box carrying on with "
            "a dropped packet would produce a plausible score vector computed "
            "without the data it asked for."
        ),
    )


def _by_interface_detail(
    path: EgressPath,
    namespace: object,
) -> str:
    """The sentence for the one answer no §5.2 placement can produce."""
    egress = _egress_of(namespace)
    return (
        f"an egress attempt from box "
        f"{getattr(namespace, 'component', '')!r} was admitted: its "
        f"network namespace holds {len(egress)} interface(s) that could carry "
        f"the packet off the box ({list(egress)!r}), so there is no "
        f"namespace-level rejection to make and the attempt proceeds to "
        f"{path.describe()}. {_row_sentence()}, and this is that row not "
        f"holding: the namespace the gate consulted has an egress surface, "
        f"which no placement built the way §5.2 requires can produce. Reading "
        f"reason 'by-interface' is itself the audit finding — the placement was "
        f"hand-built or reported wrong, and the box has a path out that this "
        f"law did not give it (feature 158)."
    )


def reject_egress(subject: object, namespace: object) -> NetworkDecision:
    """Answer one attempt: admitted only when the box's namespace holds an
    interface that could carry it.

    The gate, and the one place this law is actually applied — every other verb
    in this module (:meth:`SandboxNetwork.check`, :meth:`NetworkDecision.
    require`) reaches this function rather than re-deciding.  Nothing is raised
    here for a refusal, for the reason features 157's, 159's, 160's and 162's
    gates raise nothing: §6.1 dispatches thousands of unattended candidates and
    *"this one tried to dial out"* must reach an operator as a fact about a run
    rather than as a crashed evaluator, while a caller that must not proceed
    turns the answer into an exception with :meth:`NetworkDecision.require`.

    The order of the checks is the order of the sentence, with the box's
    *placement* settled before the attempt's own path — an unplaced box is
    answered before anything is asked about the attempt, then the membership,
    then the interfaces, which are the only thing that can admit.  Both
    placement refusals refuse the attempt as well, so a caller branching on
    :attr:`NetworkDecision.rejected` is safe whichever way the configuration
    drifted; :attr:`NetworkDecision.at_namespace` is what tells the two repairs
    apart.

    ``namespace`` is a :class:`NetworkNamespace` or ``None``: ``None`` is
    :attr:`NetworkReason.NOT_PLACED` rather than an error, because "this box was
    never placed" is a state a caller can be in and the honest answer to it is a
    refusal rather than a traceback.
    """
    path = _subject_path(subject)
    origin = _subject_origin(subject)

    if namespace is None:
        return NetworkDecision(
            admitted=False,
            reason=NetworkReason.NOT_PLACED,
            detail=_not_placed_refusal(path),
            path=path,
        )

    if not _is_placement(namespace):
        raise NamespacePlacementError(
            f"{NAMESPACE_REQUIRED_CODE}: the placement to judge an egress "
            f"attempt against must be a namespace reporting the interfaces it "
            f"holds, or None, got {type(namespace).__name__}. A placement is "
            f"the namespace a box runs in — the interfaces a runtime reported — "
            f"and a gate handed something else has no egress surface to "
            f"consult, which is a fact about the caller rather than about the "
            f"attempt (feature 158)."
        )

    component = getattr(namespace, "component", "") or ""
    if origin and component and origin != component:
        return NetworkDecision(
            admitted=False,
            reason=NetworkReason.UNKNOWN_SANDBOX,
            detail=_unknown_sandbox_refusal(path, namespace),
            path=path,
            namespace=namespace,
        )

    if _egress_of(namespace):
        return NetworkDecision(
            admitted=True,
            reason=NetworkReason.BY_INTERFACE,
            detail=_by_interface_detail(path, namespace),
            path=path,
            namespace=namespace,
        )

    return NetworkDecision(
        admitted=False,
        reason=NetworkReason.AT_NAMESPACE,
        detail=_at_namespace_refusal(path, namespace),
        path=path,
        namespace=namespace,
    )


def egress_rejected(subject: object, namespace: object) -> bool:
    """Whether an attempt was refused — the one boolean.

    The convenience for a caller that does not want the decision: the same
    computation, read at its headline.  ``False`` for the one answer a
    hand-built placement produces (:attr:`NetworkReason.BY_INTERFACE`), which is
    the answer a caller *should* be surprised by — a box placed as §5.2 requires
    has no way to produce it.

    Never raises: a caller that must hear about a malformed placement calls
    :func:`reject_egress`, where the refusal is a named error rather than a
    boolean that reads like a working box.
    """
    return reject_egress(subject, namespace).rejected


def isolated_namespace(
    component: str = "",
    interfaces: Iterable[str] = (),
) -> NetworkNamespace:
    """§5.2's namespace for a box, as a value — no egress interface.

    The placement every box in this deployment is in, built the way a runtime
    would report it: the loopback the kernel creates with the namespace, and
    nothing else.  The default ``interfaces`` is empty, which is the stricter
    reading and the honest one for a caller that has not asked the runtime yet;
    a caller that wants the loopback the kernel actually creates passes
    ``("lo",)`` and gets the same egress surface, because
    :data:`LOOPBACK_NAMES` is what decides.

    Not a component and not registered: a placement belongs to one box, and a
    component held across runs that owned one would be one box's namespace
    applied to another's — the property :func:`sandbox.transfer.sandbox_transfer`
    and :func:`sandbox.payload.sandbox_payload` state for their own quantities.
    """
    return NetworkNamespace(component=component, interfaces=interfaces)


class SandboxNetwork:
    """Feature 158's law, as the value a composed application carries.

    A stateless facade over this module — the same shape
    :class:`sandbox.SandboxPayload` gives feature 159,
    :class:`sandbox.SandboxQuarantine` 161 and the other nine facades give
    theirs — so a caller holding the composed component can ask the feature's
    question, *was this egress attempt rejected at the namespace level?*,
    without importing the member's submodules by name.

    **It carries no namespace, no file descriptor and no socket.**  A namespace
    belongs to one box, and a component shared across runs that carried one
    would be a component letting two boxes share a network posture — the
    property :class:`sandbox.SandboxTransfer` states for its channel and
    :class:`sandbox.SandboxPayload` for its window, restated here because the
    quantity is the same one in its most literal form.  It does not create
    namespaces either: :meth:`namespace` builds the *value* a launcher describes
    its runtime with, which is the division feature 157 states between its
    isolation policy and the runtime that enforces it.

    **The delegation is deliberately thin** — each verb is one call into this
    module — because a second implementation of the interface rule or the
    refusal sentence here would be a second thing to keep in sync, and the
    member's one-provenance rule exists so that cannot happen.
    """

    __slots__ = ()

    def check(self, subject: object, namespace: object) -> NetworkDecision:
        """Answer whether ``subject`` was rejected at the namespace level.

        ``subject`` is an :class:`EgressPath` or any object carrying an
        ``origin`` — feature 149's :class:`infra.security.sandbox_egress.
        EgressAttempt` included.  Returns a :class:`NetworkDecision` whose
        ``admitted`` is ``False`` for every box placed as §5.2 requires.
        Nothing raises for a refusal, for the reason feature 157's gate raises
        nothing.
        """
        return reject_egress(subject, namespace)

    def require(self, subject: object, namespace: object) -> None:
        """Return ``None`` if the attempt was rejected, else raise.

        The launcher's verb, and the one line that makes *"rejects egress at the
        namespace level"* enforced where the box is placed rather than
        remembered: put it on the line after the spawn and an attempt that could
        have crossed becomes the member's own
        :class:`~sandbox.errors.EgressRejected` rather than an ordinary trial
        outcome for a run nothing confined.  Note that it raises for the box
        that is *not* placed too — an unplaced box is a box whose egress nothing
        rejected, and a launcher must hear about it.
        """
        self.check(subject, namespace).require()

    def namespace(
        self,
        component: str = "",
        interfaces: Iterable[str] = (),
    ) -> NetworkNamespace:
        """The namespace a box was placed in, as a value the caller builds.

        The per-box seam, the counterpart of
        :meth:`sandbox.transfer.SandboxTransfer.channel` and
        :meth:`sandbox.quarantine.SandboxQuarantine.tree`: the component holds
        no namespace, so a caller that needs one builds it here — or, more
        usually, a launcher builds it from what its runtime reported and hands
        it to :meth:`check`.  Both roads reach the same object.
        """
        return NetworkNamespace(component=component, interfaces=interfaces)

    def isolated(self, namespace: object) -> bool:
        """Whether a box is placed as §5.2 requires — the read side.

        *What is this box's network posture?* is a question a deployment should
        be able to answer without running a candidate to find out, and answering
        it from the placement is what makes "the sandbox has no network" a fact
        about the runtime configuration rather than a claim in a runbook.
        ``False`` for a box that was handed no namespace at all, which is the
        conservative reading: a box nobody placed is not a box with no network,
        it is one whose network nobody has spoken about.
        """
        if not _is_placement(namespace):
            return False
        return not _egress_of(namespace)

    def interfaces(self, namespace: object) -> tuple[str, ...]:
        """The interfaces that could carry a packet off a box, in order.

        The other half of the read side, and the one a reviewer checks first: an
        operator asking *which interface does this box hold?* gets the names
        rather than a count, because a box holding ``lo`` and a box holding
        ``eth0`` are both "one interface" and are opposite facts.  Empty for a
        box placed as §5.2 requires, and empty for a namespace this law cannot
        read.
        """
        if not _is_placement(namespace):
            return ()
        return _egress_of(namespace)


def sandbox_network() -> SandboxNetwork:
    """The network law, for a caller that wants it directly.

    Not a component and not registered: a component whose builder *ran* the law
    would have nothing to run it *on*, since the law needs an attempt and the
    namespace the attempt was made in, both handed in by the caller.  This is
    the module-level convenience the member's own tests and any operator script
    reach, and it is the same call :func:`sandbox.build_sandbox_network` makes
    minus the composition.
    """
    return SandboxNetwork()
