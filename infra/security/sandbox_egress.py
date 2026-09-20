"""Feature 149's law: a sandbox's egress is denied, all of it, by default.

app_spec.xml, "Trust Zone Isolation & Secrets", feature 149: *System
denies all egress from sandboxes by default, which rejects any attempt
to reach the data lake over the network.*  docs/nullius-tech-
architecture.md §17 fixes the posture in one line — "Z1 sandboxes:
egress denied by default." — and the sentence decomposes into four
claims, each owned here as a seam rather than a comment:

* **denies all egress** — the totality, and the compile-time law that
  carries it.  :func:`compile_sandbox_egress_policy` refuses — fail
  closed, before anything is applied — a document that grants *any*
  sandbox *any* egress rule: any port, any protocol, any destination.
  Nothing is excepted because nothing needs to be: everything a sandbox
  legitimately exchanges travels a *channel*, and a channel is not
  egress — code goes in and comes out through the orchestrator's
  conduit (:mod:`infra.security.provider_boundary`, feature 150), and
  data goes in as a pre-sliced payload over the IPC channel (features
  120 and 159).  The refusal (:class:`SandboxEgressRuleRejected`) names
  the offending rule so the drift is findable, and refuses the whole
  document rather than skipping the rule, for the reason the category's
  anchor law gives: a policy applied with rules silently dropped is one
  whose file and whose sandbox disagree, and that disagreement is where
  the next drift lives.  The shape is feature 156's dual — that law
  empties a live host's *ingress*
  (:class:`infra.security.network_policy.IngressRuleRejected`), this
  one empties a sandbox's *egress* — and the grammar is shared: an
  egress rule parses through the same
  :class:`~infra.security.network_policy.IngressRule`, one grammar, two
  directions, so the totality of the refusal does not depend on the
  spelling a drift was written in.

* **from sandboxes** — the subject is plural and held by *membership*,
  not by name.  The law keys on the document's ``sandboxes`` list —
  every Z1 box the deployment runs; the committed artifact carries the
  two §3's component map draws, the signal sandbox and the policy
  runtime — so a third sandbox inherits the empty egress surface by
  being listed, not by someone remembering to copy a rule onto it.  The
  gate honours the same membership: an attempt whose origin the policy
  does not list is itself rejected
  (:attr:`EgressReason.UNKNOWN_SANDBOX`), because an unlisted sandbox
  is not a gift of egress — it is a box this policy does not vouch
  for, and default is what it gets.

* **by default** — the posture claim, and the reason the failure mode
  is safe.  The default is not "open until denied" but "closed with
  nothing to open": a compiled policy holds zero allowances because
  zero were written, and the compiler refuses to compile one however it
  is written, so granting egress would take an act the policy grammar
  cannot express.  The *absent* half is refused exactly like the
  granted one, because "absent" and "held empty by law" are different
  promises and only the second is feature 149's.  The committed
  document (:data:`COMMITTED_SANDBOX_EGRESS_POLICY`) *is* the default —
  the posture an operator applies without writing a stanza, read and
  compiled through the same refusal as any change to it.

* **which rejects any attempt to reach the data lake over the
  network** — the consequent, the named asset, and the gate's headline
  reason.  §1 P1 keeps the data snapshots in a read-only zone that
  LLM-authored code has "no write credential for, and no network path
  to"; §1 P4 keeps the lake unmounted — the sandbox "receives a
  pre-sliced, materialized array containing only data at or before t",
  so the network is not a slow path to the data but no path at all;
  and the layout table's own line for the lake is "Parquet + DuckDB;
  no server" — there is no listener to reach even before this policy
  refused the attempt, which is why the gate is defense in depth
  rather than the only control.  :func:`authorize_egress` answers
  every attempt: one whose destination is the lake — by its name, or
  by an address inside the networks the policy says are its — is
  rejected with :attr:`EgressReason.NO_NETWORK_PATH_TO_DATA_LAKE`,
  §1 P1's own words, because the rejection should say the true thing:
  not "you are not allowed" but "there is no path".  Every other
  attempt — an external host, an exchange, the session broker the live
  zone dials freely, loopback itself — falls to
  :attr:`EgressReason.EGRESS_DENIED_BY_DEFAULT`, §17 verbatim.

**The refusal is raised; the rejection is returned.**  Two audiences,
two shapes, one law.  A policy document is written by trusted code —
an operator, a CI check — so a document that drifts open is refused
with an exception the caller cannot ignore, exactly as feature 156's
compile refusals are (:class:`infra.security.network_policy.
ZonePolicyError`).  An egress attempt is made by *untrusted* code
inside the sandbox and arrives in every shape, well-formed and hostile
alike, so the gate *answers* attempts the way the access gate answers
arrivals (:func:`infra.security.host_access.authorize_access`): a
decision for every attempt, raised for none, with the denial computed
rather than assumed — the gate consults the origin's compiled surface
(:meth:`SandboxEgress.admits`), the compiler holds that surface empty,
and the rejection is that emptiness arriving at its answer.  The
consultation is written, not deleted, so a reader can see the gate
denies *because the surface is empty* — and the branch an allowance
would take (:attr:`EgressReason.BY_ALLOWANCE`) can never be reached
from a compiled policy, which is itself an audit property: a decision
reading ``by-allowance`` is proof the surface it consulted was not
compiled.

**Honest limits.**  This module is the policy-time law, not the runtime
enforcement: at runtime the sandbox runs in a network namespace with
no interfaces, so egress is rejected at the namespace level rather
than by firewall rule (§2's "Sandboxed: no network"; feature 158's
plugin) — and like every Python object graph, a hand-assembled policy
can hold an allowance no compiler would issue.  What holds is that the
committed document cannot drift open without the compile failing, that
the gate derives its answer from the compiled surface rather than a
hardcoded denial, and that even a rogue allowance cannot read as
permission to reach the data lake — the lake's rejection is checked
before the surface is consulted, so §1 P1 outranks everything.
Enforce with network policy, never with prompt instructions (§2): "a
prompt is not a security boundary", and this module is the network
policy.

Stdlib-only, like the rest of this tree.  Nothing here dials a
network; this module is the law the runtime enforcement is written
against, and the artifact (:data:`COMMITTED_SANDBOX_EGRESS_POLICY`)
is what an operator applies.
"""

from __future__ import annotations

import enum
import ipaddress
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Final

from .network_policy import IngressRule, PolicyDocumentError

__all__ = [
    "COMMITTED_SANDBOX_EGRESS_POLICY",
    "POLICY_KIND",
    "DataLake",
    "EgressAttempt",
    "EgressDecision",
    "EgressPolicyDocumentError",
    "EgressReason",
    "MissingDataLake",
    "SandboxEgress",
    "SandboxEgressError",
    "SandboxEgressPolicy",
    "SandboxEgressRuleRejected",
    "authorize_egress",
    "committed_sandbox_egress_policy",
    "compile_sandbox_egress_policy",
    "load_sandbox_egress_policy",
]

#: What kind of document this module compiles.  A fixed marker, checked
#: at compile time, so a JSON file that happens to carry a
#: ``sandboxes`` key cannot be read as the egress policy of the zone:
#: a document that does not say what it is cannot be trusted to say
#: what it allows.
POLICY_KIND: Final[str] = "sandbox-egress"

#: The committed egress policy of the sandboxes — the JSON artifact
#: this feature's law is written against, and the thing an operator
#: applies.  ``infra/security/`` is shared by the whole "Trust Zone
#: Isolation & Secrets" category, so the document is named for its
#: law, as the zone document beside it is named for its zone.
COMMITTED_SANDBOX_EGRESS_POLICY: Final[Path] = Path(__file__).with_name(
    "sandbox_egress_policy.json"
)


class SandboxEgressError(Exception):
    """Base of the sandbox-egress taxonomy.

    One base class so a caller — a CI check that recompiles the
    committed document, an operator script proposing a change to it, a
    renderer about to print the surface — can catch every failure of
    the compile path with a single ``except``.  The subclasses split by
    *which contract* was violated, never by which line of code failed,
    in the same discipline as :mod:`infra.security.network_policy`'s
    and :mod:`infra.security.provider_boundary`'s taxonomies.
    """


class EgressPolicyDocumentError(SandboxEgressError):
    """The document is not a sandbox egress policy at all.

    A malformed sandbox block, an absent egress half, a duplicate
    sandbox name, an address that is not a network.  The compiler
    fails closed on all of them: a document it cannot read completely
    is a document it will not partially trust — and this includes the
    parse failures of the shared rule grammar, which arrive here
    translated rather than leaking
    :class:`infra.security.network_policy.PolicyDocumentError` through
    the seam, so a caller catching this taxonomy catches all of it.
    """


class SandboxEgressRuleRejected(SandboxEgressError):
    """The law: a sandbox carries an egress rule.

    Raised by :func:`compile_sandbox_egress_policy` for *any* egress
    rule on *any* sandbox — the whole document is refused, not the one
    rule skipped, because a policy applied with the rule silently
    dropped is a policy whose file and whose sandbox disagree, and the
    disagreement is where the next drift lives.  The dual of
    :class:`infra.security.network_policy.IngressRuleRejected`, which
    refuses a live-trading host an ingress rule with the same
    whole-document stance.
    """


class MissingDataLake(SandboxEgressError):
    """A sandbox egress policy that names no data lake.

    The feature's rejection is named for the attempt this law exists to
    answer — reaching the data lake over the network — and a policy
    that cannot say which name and which networks are the lake could
    never recognize that attempt when it arrived.  It would deny it,
    but by the default and in the default's words: the same protection
    worn without its reason, and the reason is the part an operator
    reading a trace needs.  Refused at compile time, fail closed — the
    dual of :class:`infra.security.network_policy.MissingBrokerEgress`,
    which refuses a zone document that cannot reach the mechanism its
    promise presupposes.
    """


def _require_mapping(value: Any, what: str) -> Mapping[str, Any]:
    """Return ``value`` as a string-keyed mapping, refusing anything else."""
    if not isinstance(value, Mapping):
        raise EgressPolicyDocumentError(
            f"{what} must be a mapping, got {type(value).__name__}: "
            f"{value!r}. A sandbox egress policy is a structured "
            f"document, and a compiler that guessed at the meaning of a "
            f"stray list or string would be writing policy rather than "
            f"reading it — it is refused instead, fail closed (feature "
            f"149: the sandbox's empty egress surface is only as "
            f"trustworthy as the compile that checked it)."
        )
    return value


def _require_str(value: Any, what: str) -> str:
    """Return ``value`` as a non-empty string, refusing anything else."""
    if not isinstance(value, str) or not value:
        raise EgressPolicyDocumentError(
            f"{what} must be a non-empty string, got {value!r}. The "
            f"policy names its lake and its sandboxes; a blank or "
            f"non-string name is not a name, and the compiler will not "
            f"invent one (feature 149)."
        )
    return value


def _describe_egress_rule(raw: Any, what: str) -> str:
    """Parse one raw egress rule and return it in egress's own words.

    The parse is the shared grammar's (:meth:`IngressRule.from_document`
    with ``destinations`` as the endpoint list), so a rule the refusal
    names is a rule that actually parses — validated ports, one span,
    real endpoints — rather than an echo of whatever drift was written.
    Its failures are translated at the seam: this module raises
    :class:`EgressPolicyDocumentError`, never the shared grammar's
    own type, so a caller catching this taxonomy catches all of it.

    :meth:`IngressRule.describe` is not used even though it exists,
    because it spells the endpoint half ``from`` — ingress's word; an
    egress rule says ``to``.
    """
    try:
        rule = IngressRule.from_document(raw, what, endpoints="destinations")
    except PolicyDocumentError as drift:
        raise EgressPolicyDocumentError(
            f"{what} cannot be read as an egress rule: {drift}. The "
            f"grammar is shared with the zone policy's rules (one "
            f"grammar, two directions), and a drift that cannot even "
            f"parse is refused here rather than leaked through the seam "
            f"as another module's error — the whole document is "
            f"refused either way, fail closed (feature 149)."
        ) from drift
    lo, hi = rule.port_range
    span = str(lo) if lo == hi else f"{lo}-{hi}"
    return f"{rule.protocol}/{span} to {', '.join(repr(d) for d in rule.sources)}"


class DataLake:
    """The data lake's network identity: its name and its networks.

    The asset the feature's rejection is named for, held as the two
    spellings an attempt can reach for it by — the host name the
    deployment writes in its documents, and the address ranges the
    lake's disks live on.  Recognition is the whole job: the gate
    cannot reject an attempt "to reach the data lake" in the lake's
    own words unless the policy said which name and which networks
    are the lake, which is why a document without this block is
    refused (:class:`MissingDataLake`) rather than compiled with the
    claim quietly unread.

    Networks are parsed, not stored as strings: a CIDR that does not
    parse is a typo, and it is refused at compile time — an address
    list the matcher would silently never match is an allowance in
    disguise.
    """

    __slots__ = ("name", "networks")

    def __init__(
        self,
        *,
        name: str,
        networks: tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...],
    ) -> None:
        self.name = name
        self.networks = networks

    def reached_by(self, destination: str) -> bool:
        """Whether an attempt at ``destination`` reaches for this lake.

        The name is matched by equality and the networks by containment
        — ``10.8.0.0/24`` covers ``10.8.0.7`` — the same two spellings
        the zone policy's rules match sources by, read here in the
        other direction.  A destination that is neither the name nor an
        address inside any network is not this lake, and the attempt at
        it falls to the default instead.
        """
        if destination == self.name:
            return True
        try:
            address = ipaddress.ip_address(destination)
        except ValueError:
            return False
        return any(address in network for network in self.networks)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        networks = ", ".join(str(network) for network in self.networks)
        return f"DataLake(name={self.name!r}, networks=[{networks}])"


class SandboxEgress:
    """One sandbox's compiled egress surface: empty, by law.

    What :func:`compile_sandbox_egress_policy` hands out per sandbox —
    and the object the gate consults, so its denial is *derived* from
    the compiled surface rather than hardcoded.  :meth:`admits` is a
    real consultation over :attr:`allowances`; the compiler holds
    those allowances empty (refusing any document that would fill
    them), so under every compiled policy the consultation admits
    nothing.  A test can build a surface with an allowance by hand to
    prove the derivation is real — and the gate's answer on such a
    surface is itself the audit finding, because no compiled policy
    can produce it.

    ``allowances`` defaults to the empty tuple, and that default *is*
    the feature's posture: "by default" is the surface a sandbox has
    before anything is written on it.  The compiler is what keeps it
    that way.
    """

    __slots__ = ("allowances", "name")

    def __init__(
        self, *, name: str, allowances: tuple[IngressRule, ...] = ()
    ) -> None:
        self.name = name
        self.allowances = allowances

    def admits(self, port: int, protocol: str, destination: str) -> bool:
        """Whether any allowance covers this dial-out.

        Computed, never assumed: ``any`` over the compiled allowances,
        each asked whether it covers ``(port, protocol, destination)``
        the way an ingress rule covers an arrival.  For a compiled
        sandbox the tuple is empty and the answer is ``False`` for
        every attempt — the mechanism is the emptiness, not a hardcoded
        denial, which is what makes the gate's rejection checkable
        rather than taken from the prose.
        """
        return any(
            rule.admits(port, protocol, destination)
            for rule in self.allowances
        )

    def egress_spans(self) -> tuple[tuple[int, int], ...]:
        """The egress port spans this surface would open, as written.

        Spans, not a port list, so a range rule would stay one entry
        and the answer stays total whatever a hand-built surface holds.
        For every compiled sandbox it is ``()`` — the inspectable form
        of "denies all egress", the same role
        :meth:`infra.security.network_policy.HostPolicy.inbound_spans`
        plays for the live host's empty ingress.
        """
        return tuple(rule.port_range for rule in self.allowances)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return f"SandboxEgress(name={self.name!r}, allowances={self.allowances!r})"


class SandboxEgressPolicy:
    """A compiled policy: the lake named, every sandbox's surface empty.

    What :func:`compile_sandbox_egress_policy` returns is not the
    document — it is the document *plus* the guarantee that no sandbox
    in it carries an egress allowance.  Holders of a
    :class:`SandboxEgressPolicy` (the gate, an operator script, a CI
    check that recompiles the committed artifact) cite that guarantee
    rather than re-derive it, which is why the gate's default rejection
    can say "the compiled egress surface is empty" and mean it.
    """

    __slots__ = ("_sandboxes", "data_lake", "kind")

    def __init__(
        self,
        *,
        kind: str,
        data_lake: DataLake,
        sandboxes: dict[str, SandboxEgress],
    ) -> None:
        self.kind = kind
        self.data_lake = data_lake
        self._sandboxes = sandboxes

    def sandbox(self, name: str) -> SandboxEgress | None:
        """The named sandbox's surface, or ``None`` — the gate decides
        what an unknown origin means (a rejection), not the lookup."""
        return self._sandboxes.get(name)

    def sandboxes(self) -> tuple[SandboxEgress, ...]:
        """Every sandbox the policy covers, in document order."""
        return tuple(self._sandboxes.values())


def compile_sandbox_egress_policy(document: Any) -> SandboxEgressPolicy:
    """Compile a sandbox egress document, refusing one that grants anything.

    The seam the whole feature turns on.  The document is read whole —
    marker, data lake, sandboxes, in that order — each sandbox's egress
    half held to the law (written, and empty), and only then is a
    :class:`SandboxEgressPolicy` handed out.  A refusal propagates as
    an exception, so a caller cannot accidentally continue with a
    half-trusted surface: the document that would have granted the
    sandbox egress is never applied, which is the compile-time half of
    "System denies" (feature 149).

    The law is checked over the *raw* rule list, so its totality does
    not depend on which spelling a drift was written in — and the
    first offending rule is parsed through the shared grammar anyway,
    so the refusal names a rule that actually parses: validated ports,
    one span, real destinations.
    """
    doc = _require_mapping(document, "sandbox egress policy document")
    marker = _require_str(doc.get("policy"), "sandbox egress policy 'policy'")
    if marker != POLICY_KIND:
        raise EgressPolicyDocumentError(
            f"a sandbox egress policy must declare itself "
            f"{POLICY_KIND!r}, got {marker!r}. A document that does not "
            f"say what it is cannot be trusted to say what it allows, "
            f"and a stray JSON file carrying a 'sandboxes' key is not "
            f"this policy — refused, fail closed (feature 149)."
        )

    data_lake = _compile_data_lake(doc.get("data_lake"))

    raw_sandboxes = doc.get("sandboxes")
    if not isinstance(raw_sandboxes, Sequence) or isinstance(
        raw_sandboxes, (str, bytes)
    ):
        raise EgressPolicyDocumentError(
            f"a sandbox egress policy's 'sandboxes' must be a list of "
            f"sandbox blocks, got {raw_sandboxes!r}. The sandboxes list "
            f"is the law's whole subject — 'denies all egress *from "
            f"sandboxes*' — and a document that cannot enumerate them "
            f"cannot be compiled (feature 149)."
        )

    sandboxes: dict[str, SandboxEgress] = {}
    for index, raw_sandbox in enumerate(raw_sandboxes):
        block = _require_mapping(raw_sandbox, f"sandbox #{index + 1}")
        name = _require_str(block.get("name"), f"sandbox #{index + 1} 'name'")
        what = f"sandbox {name!r}"
        if name in sandboxes:
            raise EgressPolicyDocumentError(
                f"{what} appears twice in the policy. Two blocks with one "
                f"name is not two sandboxes, it is one sandbox described "
                f"twice — and the applied policy would be whichever block "
                f"came last, which is drift with extra steps. Refused "
                f"(feature 149)."
            )
        raw_rules = block.get("egress")
        if raw_rules is None:
            raise EgressPolicyDocumentError(
                f"{what} 'egress' is absent. The empty list is a sandbox's "
                f"whole egress vocabulary, and it must be written — a "
                f"compiler that read an absent half as an empty one would "
                f"be turning silence into the strongest promise the "
                f"document makes. 'Absent' and 'held empty by law' are "
                f"different promises, and only the second one is feature "
                f"149's (refused, fail closed)."
            )
        if not isinstance(raw_rules, Sequence) or isinstance(
            raw_rules, (str, bytes)
        ):
            raise EgressPolicyDocumentError(
                f"{what} 'egress' must be a list of rules (empty for "
                f"none), got {raw_rules!r}. The empty list is a sandbox's "
                f"whole egress vocabulary — a missing or malformed one is "
                f"refused rather than read as empty, because 'absent' and "
                f"'held empty by law' are different promises (feature "
                f"149)."
            )
        if raw_rules:
            described = _describe_egress_rule(
                raw_rules[0], f"{what} egress rule #1"
            )
            raise SandboxEgressRuleRejected(
                f"{what} carries an egress rule: {described}. §17 fixes a "
                f"sandbox's egress posture absolutely — Z1 sandboxes: "
                f"egress denied by default — and nothing a sandbox "
                f"legitimately exchanges travels the network: code goes "
                f"in and out through the orchestrator's conduit (feature "
                f"150) and data arrives as a pre-sliced payload over the "
                f"channel (§1 P4; features 120 and 159), so there is no "
                f"allowance any destination could earn — not the data "
                f"lake, not the session broker, not 0.0.0.0/0. The whole "
                f"document is refused, not the rule skipped — a policy "
                f"applied with rules silently dropped is one whose file "
                f"and whose sandbox disagree, and that disagreement is "
                f"where the next drift lives (feature 149: all egress "
                f"denied by default, so an attempt to reach the data "
                f"lake over the network finds nothing to fall back to)."
            )
        sandboxes[name] = SandboxEgress(name=name)

    return SandboxEgressPolicy(
        kind=marker, data_lake=data_lake, sandboxes=sandboxes
    )


def _compile_data_lake(raw: Any) -> DataLake:
    """Compile the data lake block, refusing a policy that omits it.

    The lake is the asset the feature's rejection is named for; see
    :class:`MissingDataLake` for why a policy that cannot recognize
    the attempt this law answers is refused rather than compiled.
    """
    if raw is None:
        raise MissingDataLake(
            "the sandbox egress policy names no data lake. The "
            "feature's rejection is named for the attempt this law "
            "exists to answer — reaching the data lake over the "
            "network — and a policy that cannot say which name and "
            "which networks are the lake could never recognize that "
            "attempt when it arrived: it would deny it, but by the "
            "default and in the default's words, which is the same "
            "protection worn without its reason. Refused at compile "
            "time, fail closed (feature 149)."
        )
    block = _require_mapping(raw, "the policy's 'data_lake'")
    name = _require_str(block.get("name"), "the data lake's 'name'")
    raw_addresses = block.get("addresses")
    if (
        not isinstance(raw_addresses, Sequence)
        or isinstance(raw_addresses, (str, bytes))
        or not raw_addresses
    ):
        raise EgressPolicyDocumentError(
            f"the data lake's 'addresses' must be a non-empty list of "
            f"CIDRs, got {raw_addresses!r}. An attempt can reach for the "
            f"lake by name or by address, and a lake with no networks "
            f"named is one the gate can only ever half-recognize — the "
            f"address-shaped attempt would fall to the default's words "
            f"instead of the lake's own (feature 149)."
        )
    networks = tuple(
        _validated_network(address) for address in raw_addresses
    )
    return DataLake(name=name, networks=networks)


def _validated_network(value: Any) -> ipaddress.IPv4Network | ipaddress.IPv6Network:
    """Return ``value`` as a parsed network, refusing anything else.

    Parsed at compile time rather than matched at attempt time, so a
    typo'd CIDR is a compile failure instead of an address list the
    matcher would silently never match — an unrecognized network is an
    allowance in disguise.  Non-strict, matching the zone policy's
    containment doctrine: ``10.8.0.7/24`` names the /24 it lives in.
    """
    if not isinstance(value, str):
        raise EgressPolicyDocumentError(
            f"a data lake address must be a CIDR string, got {value!r} "
            f"({type(value).__name__}). An address is a network the gate "
            f"matches containment against, and a value that cannot be "
            f"one is refused rather than stored unmatched (feature 149)."
        )
    try:
        return ipaddress.ip_network(value, strict=False)
    except ValueError:
        raise EgressPolicyDocumentError(
            f"a data lake address must be a CIDR, got {value!r}. A "
            f"network that does not parse is a typo, and a typo kept in "
            f"the list is an address range the gate would silently never "
            f"recognize — the attempt it should have named falls to the "
            f"default's words instead. Refused at compile time (feature "
            f"149)."
        ) from None


class EgressReason(enum.StrEnum):
    """Why a decision came out the way it did — the audit vocabulary.

    One enumeration carries the acceptance and the rejection reasons,
    because a decision's reason is one fact with two polarities, and
    the audit line should read the same either way: ``egress-denied-
    by-default`` is §17's posture verbatim, and ``no-network-path-to-
    data-lake`` is §1 P1's own claim about the snapshots, not a rule
    this policy invented.
    """

    #: Rejected: the destination is the data lake — by name, or by an
    #: address inside the networks the policy says are its — and the
    #: sandbox has no network path to it (§1 P1, §1 P4).  The reason
    #: the feature's sentence gives its own name to.
    NO_NETWORK_PATH_TO_DATA_LAKE = "no-network-path-to-data-lake"

    #: Rejected: every attempt that is not the lake's own case.  The
    #: sandbox's compiled egress surface is empty, so there is no
    #: allowance this attempt could have matched — §17 verbatim.
    EGRESS_DENIED_BY_DEFAULT = "egress-denied-by-default"

    #: Rejected: the attempt's origin is not a sandbox the policy
    #: covers.  An unlisted sandbox is not a gift of egress; it is a
    #: box this policy does not vouch for, and default is what it gets.
    UNKNOWN_SANDBOX = "unknown-sandbox"

    #: Admitted by an allowance on the consulted surface.  No compiled
    #: policy can produce this reason — the compiler refuses a sandbox
    #: any allowance at all — so a decision reading ``by-allowance`` is
    #: itself the audit finding: the surface was hand-built, not
    #: compiled (feature 149).
    BY_ALLOWANCE = "by-allowance"


class EgressAttempt:
    """One dial-out from a sandbox, as presented.

    Deliberately unvalidated beyond assignment: the gate models what
    untrusted code inside the sandbox reached for, hostile shapes
    included, and *answers* them rather than refusing to parse them —
    the same stance :class:`infra.security.host_access.AccessRequest`
    takes for arrivals.  ``origin`` names the sandbox the attempt came
    from and ``destination`` is the host name or address it dialed,
    the two facts every reason below reads.
    """

    __slots__ = ("destination", "origin", "port", "protocol")

    def __init__(
        self,
        *,
        origin: str,
        destination: str,
        port: int,
        protocol: str = "tcp",
    ) -> None:
        self.origin = origin
        self.destination = destination
        self.port = port
        self.protocol = protocol

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return (
            f"EgressAttempt(origin={self.origin!r}, "
            f"destination={self.destination!r}, port={self.port}, "
            f"protocol={self.protocol!r})"
        )


class EgressDecision:
    """The gate's whole answer: allowed, why, and in what words.

    ``allowed`` is typed as a bool and, under this law, is always
    ``False`` — the field exists because the decision is the audit
    record a caller reads, and "was it allowed" is the question an
    auditor asks of any gate; the law fixes the value, the way the
    compile fixes every compiled surface empty.  ``detail`` carries
    the operator-facing sentence — the one place the mechanism
    explains itself at rejection time, naming the origin, the
    destination and the surface consulted.
    """

    __slots__ = ("allowed", "detail", "reason")

    def __init__(self, *, allowed: bool, reason: EgressReason, detail: str) -> None:
        self.allowed = allowed
        self.reason = reason
        self.detail = detail

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return f"EgressDecision(allowed={self.allowed}, reason={self.reason!r})"


def authorize_egress(
    attempt: EgressAttempt, policy: SandboxEgressPolicy
) -> EgressDecision:
    """Answer one egress attempt from a sandbox: rejected, always.

    The order of the checks is the order of the sentence.  The origin
    is settled first — the gate answers for the compiled policy's
    sandboxes, and an unknown origin has no surface to be evaluated
    against.  The data lake is settled second, *before* the surface is
    consulted: the rejection named for the lake is the feature's own
    headline, and §1 P1 outranks everything — even a rogue,
    hand-assembled allowance can never read as permission to reach the
    lake.  Everything else is settled by the surface, which the
    compiler holds empty, so it falls out the bottom rejected with
    §17's own words — the emptiness arriving at its answer.
    """
    sandbox = policy.sandbox(attempt.origin)
    if sandbox is None:
        return EgressDecision(
            allowed=False,
            reason=EgressReason.UNKNOWN_SANDBOX,
            detail=(
                f"egress attempt claims origin {attempt.origin!r}, which "
                f"is not a sandbox of policy {policy.kind!r}. The gate "
                f"answers for the compiled policy and nothing else; an "
                f"origin outside it has no surface to be evaluated "
                f"against and is denied — an unlisted sandbox is not a "
                f"gift of egress, it is a box this policy does not vouch "
                f"for, and default is what it gets (feature 149)."
            ),
        )

    lake = policy.data_lake
    if lake.reached_by(attempt.destination):
        networks = ", ".join(
            str(network) for network in lake.networks
        )
        return EgressDecision(
            allowed=False,
            reason=EgressReason.NO_NETWORK_PATH_TO_DATA_LAKE,
            detail=(
                f"egress attempt from sandbox {attempt.origin!r} at "
                f"{attempt.protocol}/{attempt.port} to "
                f"{attempt.destination!r} is rejected: the destination is "
                f"the data lake ({lake.name!r} on {networks}), and the "
                f"sandbox has no network path to it. §1 P1 keeps the "
                f"snapshots in a zone LLM-authored code has no network "
                f"path to; §1 P4 keeps the lake unmounted — the data a "
                f"sandbox needs arrives pre-sliced over the payload "
                f"channel, never dialed — and the lake runs Parquet + "
                f"DuckDB with no server, so there was nothing to reach "
                f"even before this policy refused the attempt (feature "
                f"149)."
            ),
        )

    if sandbox.admits(attempt.port, attempt.protocol, attempt.destination):
        # Unreachable under this law: the compiler refuses any document
        # that would put an allowance on a compiled sandbox, so no
        # compiled policy can take this branch.  It is written as a
        # consultation rather than deleted so the gate's denial is
        # derived from the compiled surface — the same consultation
        # authorize_access performs for arrivals — and an audit line
        # reading BY_ALLOWANCE is itself the finding that the surface
        # was not compiled.
        return EgressDecision(
            allowed=True,
            reason=EgressReason.BY_ALLOWANCE,
            detail=(
                f"egress attempt from sandbox {attempt.origin!r} at "
                f"{attempt.protocol}/{attempt.port} to "
                f"{attempt.destination!r} matches an allowance on its "
                f"surface. No compiled policy can produce this answer — "
                f"the compiler refuses a sandbox any egress rule at all "
                f"(feature 149) — so this decision is itself the audit "
                f"finding: the surface consulted was hand-built, not "
                f"compiled."
            ),
        )

    return EgressDecision(
        allowed=False,
        reason=EgressReason.EGRESS_DENIED_BY_DEFAULT,
        detail=(
            f"egress attempt from sandbox {attempt.origin!r} at "
            f"{attempt.protocol}/{attempt.port} to "
            f"{attempt.destination!r} is denied by default: the "
            f"sandbox's compiled egress surface is empty — §17 fixes Z1 "
            f"sandboxes' egress denied by default, and the compiler "
            f"refuses any document saying otherwise — so there is no "
            f"allowance this attempt could have matched, on no port, to "
            f"no destination. What a sandbox exchanges travels channels, "
            f"not the network: code in and out through the "
            f"orchestrator's conduit (feature 150), data in as a "
            f"pre-sliced payload (§1 P4; features 120 and 159) — and "
            f"the one call that may leave is the orchestrator's to "
            f"make, never the sandbox's (feature 149)."
        ),
    )


def load_sandbox_egress_policy(path: Path) -> SandboxEgressPolicy:
    """Load and compile the sandbox egress document at ``path``.

    JSON, read whole and compiled whole — the committed artifact
    (:data:`COMMITTED_SANDBOX_EGRESS_POLICY`) and any proposed change
    to it pass through the same :func:`compile_sandbox_egress_policy`
    refusal, so the document on disk cannot drift open without the
    compile failing.
    """
    with path.open("r", encoding="utf-8") as handle:
        document = json.load(handle)
    return compile_sandbox_egress_policy(document)


def committed_sandbox_egress_policy() -> SandboxEgressPolicy:
    """The compiled egress policy of the sandboxes as committed.

    The document this feature stands up: read from
    :data:`COMMITTED_SANDBOX_EGRESS_POLICY` and compiled through the
    same law as any change to it, so what the gate consults and what
    the operator applied are provably the same surface.  This *is* the
    "by default" of the feature's sentence — the posture the deployment
    runs with before anyone writes a stanza.
    """
    return load_sandbox_egress_policy(COMMITTED_SANDBOX_EGRESS_POLICY)
