"""Feature 156's law: the live trading host exposes no inbound port.

app_spec.xml, "Trust Zone Isolation & Secrets", feature 156: *System
rejects access to the live trading host that does not arrive through a
bastion session, because no inbound port is exposed.*  docs/nullius-
architecture.md §17 states the control in one line — "No inbound ports on
the live trading host. Access via bastion or session manager only." —
and this module is that line made structural.  The sentence decomposes
into four claims, and this module owns the middle two:

* **the live trading host** — the law's subject is a *role*, not a
  machine name.  §1 P6 fixes the topology the role lives in: research
  compute and trading compute are separate systems that *share
  libraries, never infrastructure*, so the live trading zone carries its
  own policy document (:data:`COMMITTED_ZONE_POLICY`, the JSON artifact
  an operator applies) rather than a stanza in some shared one.  The law
  keys on :data:`LIVE_TRADING_ROLE` so it holds for every host the zone
  ever grows — a second live host inherits the empty ingress surface by
  carrying the role, not by someone remembering to copy a rule.

* **because no inbound port is exposed** — the *cause*, and the claim
  that orders everything else.  The rejection is not an allowlist sat
  in front of open ports; there is no port to connect to.  That is why
  :func:`compile_zone_policy` refuses — fail closed, before anything is
  applied — a document that gives a live-trading host *any* ingress
  rule: any port, any protocol, any source.  The refusal names the
  offending rule so the drift is findable, and it does not exempt the
  bastion's own address, because a bastion *session* is an outbound
  channel the host dialed (:mod:`infra.security.bastion`), never an
  ingress allowance — an "SSH from bastion only" rule is exactly the
  drift this law exists to reject.  The doctrine is §5.2's, one zone
  up: isolation by *topology*, "not a firewall rule".

* **through a bastion session** — the single carve-out, owned by
  :mod:`infra.security.bastion` and enforced at the gate
  (:mod:`infra.security.host_access`).  Its corollary lives here: §17
  promises access *via* bastion, which presupposes the outbound path,
  so a live-trading host whose egress cannot reach the session broker
  is refused just as firmly (:class:`MissingBrokerEgress`) — that
  document does not describe a host only the bastion can reach, but a
  host *nothing* can reach, which is an outage misfiled as a policy.

* **System rejects** — two spellings of one word.  The compile-time
  spelling rejects a *document* (drift can never be applied); the
  access-time spelling rejects an *arrival*
  (:func:`infra.security.host_access.authorize_access`).  The feature's
  "because" binds them: the arrival is refused with reason
  ``no-inbound-port-exposed`` *because* the compiled surface it consults
  is empty, and the surface is empty *because* the compiler refused
  every document that tried to open it.

Stdlib-only, like the rest of the zone's tooling.  Nothing here dials a
network; this module is the policy a renderer (:mod:`infra.security.firewall`)
prints and a gate cites.
"""

from __future__ import annotations

import ipaddress
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Final

__all__ = [
    "BASTION_ROLE",
    "COMMITTED_ZONE_POLICY",
    "IngressRule",
    "IngressRuleRejected",
    "LIVE_TRADING_ROLE",
    "MissingBrokerEgress",
    "PolicyDocumentError",
    "SESSION_BROKER_DESTINATION",
    "ZonePolicy",
    "ZonePolicyError",
    "committed_zone_policy",
    "compile_zone_policy",
    "load_zone_policy",
]

#: The role the law keys on.  A host carries this role in the zone
#: document; every rule below then holds for it by construction.
LIVE_TRADING_ROLE: Final[str] = "live-trading"

#: The zone's front door.  The bastion is the one host that *may* hold an
#: inbound rule (its own SSH, from the operator allowlist) — the contrast
#: that makes "no inbound port on the live trading host" a statement about
#: the live host, not a blanket the whole zone hides under.
BASTION_ROLE: Final[str] = "bastion"

#: The egress destination every live-trading host must be able to dial:
#: the broker (§17's "bastion or session manager" — one mechanism,
#: :mod:`infra.security.bastion`) the host's session channel rides.
SESSION_BROKER_DESTINATION: Final[str] = "session-broker"

#: The committed policy document for the live trading zone — the JSON
#: artifact this feature's law is written against, and the thing an
#: operator applies.  ``infra/security/`` is shared by the whole
#: "Trust Zone Isolation & Secrets" category, so the document is named
#: for its zone, not for the feature that authored it.
COMMITTED_ZONE_POLICY: Final[Path] = Path(__file__).with_name(
    "live_trading_zone_policy.json"
)

_MAX_PORT: Final[int] = 65535


class ZonePolicyError(Exception):
    """Base of the zone-policy taxonomy.

    One base class so a caller — the access gate, a CI check that
    recompiles the committed document, an operator script — can catch
    every failure of the compile path with a single ``except``.  The
    subclasses split by *which contract* was violated, never by which
    line of code failed.
    """


class PolicyDocumentError(ZonePolicyError):
    """The document is not a zone policy at all.

    A malformed host block, an ingress rule with no port, a duplicate
    host name.  The compiler fails closed on all of them: a document it
    cannot read completely is a document it will not partially trust.
    """


class IngressRuleRejected(ZonePolicyError):
    """The law: a live-trading host carries an ingress rule.

    Raised by :func:`compile_zone_policy` for *any* ingress rule on *any*
    :data:`LIVE_TRADING_ROLE` host — the whole document is refused, not
    the one rule skipped, because a policy applied with the rule
    silently dropped is a policy whose file and whose host disagree, and
    the disagreement is where the next drift lives.
    """


class MissingBrokerEgress(ZonePolicyError):
    """A live-trading host that cannot dial the session broker.

    §17 promises access via bastion or session manager *only*, and that
    promise presupposes the outbound path: with no inbound port, the
    session channel is a connection the host itself opens to the broker
    (:mod:`infra.security.bastion`).  A live-trading host with no egress
    to :data:`SESSION_BROKER_DESTINATION` is therefore not a host only
    the bastion can reach but a host nothing can reach — an outage
    misfiled as a policy, and refused at compile time like one.
    """


def _require_mapping(value: Any, what: str) -> Mapping[str, Any]:
    """Return ``value`` as a string-keyed mapping, refusing anything else."""
    if not isinstance(value, Mapping):
        raise PolicyDocumentError(
            f"{what} must be a mapping, got {type(value).__name__}: {value!r}. "
            f"A zone policy is a structured document, and a compiler that "
            f"guessed at the meaning of a stray list or string would be "
            f"writing policy rather than reading it — it is refused instead, "
            f"fail closed (feature 156: the live trading host's empty "
            f"ingress surface is only as trustworthy as the compile that "
            f"checked it)."
        )
    return value


def _require_str(value: Any, what: str) -> str:
    """Return ``value`` as a non-empty string, refusing anything else."""
    if not isinstance(value, str) or not value:
        raise PolicyDocumentError(
            f"{what} must be a non-empty string, got {value!r}. A policy "
            f"document names its zone, its hosts and their roles; a blank "
            f"or non-string name is not a name, and the compiler will not "
            f"invent one (feature 156)."
        )
    return value


def _validated_port(value: Any, what: str) -> int:
    """Return ``value`` as a genuine port int in ``1..65535``.

    A ``bool`` is refused explicitly even though ``bool`` subclasses
    ``int`` — ``True`` is not port 1, and a rule that said so would be
    a typo wearing a type it did not earn.
    """
    if isinstance(value, bool) or not isinstance(value, int):
        raise PolicyDocumentError(
            f"{what} must be an integer port in 1..{_MAX_PORT}, got "
            f"{value!r} ({type(value).__name__}). Ports are how ingress "
            f"rules say what they open, so a rule that cannot name its "
            f"port says nothing and is refused (feature 156)."
        )
    if not 1 <= value <= _MAX_PORT:
        raise PolicyDocumentError(
            f"{what} must be an integer port in 1..{_MAX_PORT}, got "
            f"{value!r}. A port outside the range no socket can dial is "
            f"not a tighter rule, it is a typo, and it is refused rather "
            f"than silently matched-never (feature 156)."
        )
    return value


def _validated_port_span(value: Any, what: str) -> tuple[int, int]:
    """Return ``value`` as an inclusive ``(lo, hi)`` port span."""
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)) or (
        len(value) != 2
    ):
        raise PolicyDocumentError(
            f"{what} must be a two-element [lo, hi] port range, got "
            f"{value!r}. A range is the wide drift this feature's law has "
            f"to catch — 'open 30000-40000' is one rule, not eleven "
            f"thousand — so the spelling itself is held to exactly two "
            f"bounds (feature 156)."
        )
    lo = _validated_port(value[0], f"{what} lower bound")
    hi = _validated_port(value[1], f"{what} upper bound")
    if lo > hi:
        raise PolicyDocumentError(
            f"{what} must be an ascending [lo, hi] range, got "
            f"[{lo}, {hi}]. An inverted range opens nothing it names, and "
            f"a compiler that swapped the bounds would be granting a span "
            f"the document never wrote (feature 156)."
        )
    return (lo, hi)


class IngressRule:
    """One inbound allowance a *non-live* host may hold.

    The bastion's SSH from the operator allowlist is the canonical
    instance — the one inbound rule the zone contains, whose existence
    beside the live host's empty surface is the whole shape of §17.
    A live-trading host may hold *no* instance at all; that law is
    checked at compile time over the parsed rules, so this class never
    has to defend against being one.

    A rule names either a single ``port`` or an inclusive ``port_range``
    (never both, never neither), a protocol, and the sources it admits.
    A source is a CIDR (matched by containment, via :mod:`ipaddress`) or
    a literal host name (matched by equality) — the two spellings a zone
    document actually writes.
    """

    __slots__ = ("port_range", "protocol", "sources")

    def __init__(
        self,
        *,
        port_range: tuple[int, int],
        protocol: str,
        sources: tuple[str, ...],
    ) -> None:
        self.port_range = port_range
        self.protocol = protocol
        self.sources = sources

    @classmethod
    def from_document(
        cls, raw: Any, what: str, *, endpoints: str = "sources"
    ) -> IngressRule:
        """Parse one rule, refusing any drift-shaped spelling.

        The single-port and range spellings are normalised to one
        :attr:`port_range` so the law's check — *any* rule, any shape,
        any source — never has to enumerate shapes to be total.
        ``endpoints`` names the list the rule admits — ``sources`` for
        ingress (who may connect in), ``destinations`` for egress (who
        may be dialed out) — one grammar, two directions.
        """
        rule = _require_mapping(raw, what)
        has_port = "port" in rule
        has_range = "port_range" in rule
        if has_port == has_range:
            raise PolicyDocumentError(
                f"{what} must name exactly one of 'port' or 'port_range', "
                f"got {sorted(rule)!r}. A rule that named both would open "
                f"the wider of the two and say the narrower; a rule that "
                f"named neither would admit everything and say nothing — "
                f"both are refused (feature 156)."
            )
        port_range = (
            (_validated_port(rule["port"], f"{what} port"),) * 2
            if has_port
            else _validated_port_span(rule["port_range"], f"{what} port_range")
        )
        protocol = _require_str(rule.get("protocol"), f"{what} protocol").lower()
        raw_sources = rule.get(endpoints)
        if (
            not isinstance(raw_sources, Sequence)
            or isinstance(raw_sources, (str, bytes))
            or not raw_sources
        ):
            raise PolicyDocumentError(
                f"{what} {endpoints} must be a non-empty list of CIDRs or "
                f"host names, got {raw_sources!r}. A rule with no endpoint "
                f"admits no one and opens a port for nobody — not a rule "
                f"but a hole in one — and it is refused (feature 156)."
            )
        sources = tuple(
            _require_str(source, f"{what} {endpoints[:-1]}")
            for source in raw_sources
        )
        return cls(
            port_range=port_range, protocol=protocol, sources=sources
        )

    def admits(self, port: int, protocol: str, source: str) -> bool:
        """Whether this rule covers one ``(port, protocol, source)`` arrival."""
        if protocol.lower() != self.protocol:
            return False
        if not self.port_range[0] <= port <= self.port_range[1]:
            return False
        return any(
            _source_matches(candidate, source) for candidate in self.sources
        )

    def describe(self) -> str:
        """The rule in one line, for refusal messages and audit lines."""
        lo, hi = self.port_range
        span = str(lo) if lo == hi else f"{lo}-{hi}"
        return (
            f"{self.protocol}/{span} from "
            f"{', '.join(repr(s) for s in self.sources)}"
        )


def _source_matches(candidate: str, source: str) -> bool:
    """Whether ``candidate`` (a rule's source) covers ``source``.

    A CIDR covers by containment — ``10.20.0.0/24`` covers
    ``10.20.0.7`` — and anything else is a host name, covered only by
    itself.  Containment is what makes the operator allowlist a *list of
    networks*, not a list of the machines that happened to exist when it
    was written.
    """
    try:
        network = ipaddress.ip_network(candidate, strict=False)
    except ValueError:
        return candidate == source
    try:
        address = ipaddress.ip_address(source)
    except ValueError:
        return False
    return address in network


class HostPolicy:
    """One host's compiled surface: what may arrive, what it may dial.

    The two halves are deliberately asymmetric in the zone document:
    the live trading host's ingress half is empty *by law* while its
    egress half names the exchange endpoints and the session broker —
    no listener anywhere, and every connection outbound-initiated.
    """

    __slots__ = ("egress", "ingress", "name", "role")

    def __init__(
        self,
        *,
        name: str,
        role: str,
        ingress: tuple[IngressRule, ...],
        egress: tuple[IngressRule, ...],
    ) -> None:
        self.name = name
        self.role = role
        self.ingress = ingress
        self.egress = egress

    def opening_rules(
        self, port: int, protocol: str
    ) -> tuple[IngressRule, ...]:
        """The rules that open ``protocol``/``port``, whatever sources they admit.

        The distinction the gate's two rejection reasons rest on: a host
        whose :meth:`opening_rules` are empty exposes *nothing* at this
        port — the feature's ``no-inbound-port-exposed``, nothing to
        connect to — while a host whose rules open the port but name
        other sources has a front door this arrival is simply not on
        the list for (``source-not-allowed``, the bastion's SSH from
        outside the operator allowlist).  Collapsing the two would tell
        an operator to stop looking for a hole that is not there, or to
        stop looking for a list that is.

        For a live-trading host the answer is always ``()``, because
        the compiler holds its :attr:`ingress` empty by law — so every
        arrival at it takes the first reading, which is the point.
        """
        return tuple(
            rule
            for rule in self.ingress
            if rule.protocol == protocol.lower()
            and rule.port_range[0] <= port <= rule.port_range[1]
        )

    def exposes(self, port: int, protocol: str, source: str) -> bool:
        """Whether a direct arrival at ``(port, protocol)`` from ``source``
        would land on an open port — always ``False`` for a live-trading
        host, whose :attr:`ingress` the compiler holds empty."""
        return any(
            rule.admits(port, protocol, source)
            for rule in self.opening_rules(port, protocol)
        )

    def inbound_spans(self) -> tuple[tuple[int, int], ...]:
        """The inbound port spans this host exposes, as written.

        Spans, not a port list, so a range rule stays one entry and the
        answer is total whatever the document says.  The live trading
        host's is ``()`` — the inspectable form of "no inbound port is
        exposed" (:func:`infra.security.firewall.render_security_group`
        prints the same emptiness into the applied artifact).
        """
        return tuple(rule.port_range for rule in self.ingress)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return (
            f"HostPolicy(name={self.name!r}, role={self.role!r}, "
            f"ingress=({', '.join(r.describe() for r in self.ingress)}))"
        )


class ZonePolicy:
    """A compiled zone: hosts by name, with the law already enforced.

    What :func:`compile_zone_policy` returns is not the document — it is
    the document *plus* the guarantee that no live-trading host in it
    carries an ingress rule.  Holders of a :class:`ZonePolicy` (the
    access gate, the firewall renderer) can cite that guarantee rather
    than re-derive it, which is why the gate's rejection reason can say
    ``because no inbound port is exposed`` and mean it.
    """

    __slots__ = ("_hosts", "zone")

    def __init__(self, *, zone: str, hosts: dict[str, HostPolicy]) -> None:
        self.zone = zone
        self._hosts = hosts

    def host(self, name: str) -> HostPolicy | None:
        """The named host's policy, or ``None`` — the gate decides what an
        unknown destination means (a rejection), not the lookup."""
        return self._hosts.get(name)

    def hosts(self) -> tuple[HostPolicy, ...]:
        """Every host in the zone, in document order."""
        return tuple(self._hosts.values())

    def live_trading_hosts(self) -> tuple[HostPolicy, ...]:
        """Every host the law covers — the :data:`LIVE_TRADING_ROLE` ones."""
        return tuple(
            host for host in self._hosts.values() if host.role == LIVE_TRADING_ROLE
        )


def compile_zone_policy(document: Any) -> ZonePolicy:
    """Compile a zone document, refusing one that opens a live host.

    The seam the whole feature turns on.  Everything the document says
    is parsed, then the two laws are checked — *no inbound port on a
    live-trading host* (:class:`IngressRuleRejected`) and *every
    live-trading host can still dial the broker*
    (:class:`MissingBrokerEgress`) — and only then is a
    :class:`ZonePolicy` handed out.  A refusal propagates as an
    exception, so a caller cannot accidentally continue with a
    half-trusted surface: the document that would have exposed the port
    is never applied, which is the compile-time half of "System
    rejects" (feature 156).

    The laws are checked over *parsed* rules, after normalisation, so
    their totality does not depend on which spelling a drift was
    written in — single port or range, any protocol, any source
    including the bastion's own address.
    """
    doc = _require_mapping(document, "zone policy document")
    zone = _require_str(doc.get("zone"), "zone policy 'zone'")
    raw_hosts = doc.get("hosts")
    if not isinstance(raw_hosts, Sequence) or isinstance(
        raw_hosts, (str, bytes)
    ):
        raise PolicyDocumentError(
            f"zone policy 'hosts' must be a list of host blocks, got "
            f"{raw_hosts!r}. A zone is its hosts; a document that cannot "
            f"enumerate them cannot be compiled, and is refused fail "
            f"closed (feature 156)."
        )

    hosts: dict[str, HostPolicy] = {}
    for index, raw_host in enumerate(raw_hosts):
        block = _require_mapping(raw_host, f"host #{index + 1}")
        name = _require_str(block.get("name"), f"host #{index + 1} 'name'")
        what = f"host {name!r}"
        if name in hosts:
            raise PolicyDocumentError(
                f"{what} appears twice in zone {zone!r}. Two blocks with "
                f"one name is not two hosts, it is one host described "
                f"twice — and the applied policy would be whichever block "
                f"came last, which is drift with extra steps. Refused "
                f"(feature 156)."
            )
        role = _require_str(block.get("role"), f"{what} 'role'")
        ingress = _parse_rules(block.get("ingress"), f"{what} ingress")
        egress = _parse_rules(
            block.get("egress"), f"{what} egress", endpoints="destinations"
        )
        if role == LIVE_TRADING_ROLE and ingress:
            rule = ingress[0]
            raise IngressRuleRejected(
                f"host {name!r} carries the {LIVE_TRADING_ROLE!r} role and "
                f"an ingress rule: {rule.describe()}. §17 fixes the live "
                f"trading host's surface absolutely — *no inbound ports*; "
                f"access via bastion or session manager only — and a "
                f"bastion session is a channel the host dialed outbound "
                f"(:mod:`infra.security.bastion`), never an ingress "
                f"allowance, so no source exempts a rule: not the "
                f"operator allowlist, not 0.0.0.0/0, and not the bastion "
                f"itself. The whole document is refused, not the rule "
                f"skipped — a policy applied with rules silently dropped "
                f"is one whose file and whose host disagree, and that "
                f"disagreement is where the next drift lives (feature "
                f"156: no inbound port is exposed, so nothing that is not "
                f"a bastion session can arrive)."
            )
        if role == LIVE_TRADING_ROLE and not any(
            SESSION_BROKER_DESTINATION in rule.sources for rule in egress
        ):
            raise MissingBrokerEgress(
                f"host {name!r} carries the {LIVE_TRADING_ROLE!r} role but "
                f"its egress nowhere reaches "
                f"{SESSION_BROKER_DESTINATION!r}. With no inbound port, "
                f"the only path to this host is a session channel it "
                f"itself opens to the broker — remove that egress and "
                f"§17's 'access via bastion or session manager only' "
                f"describes an unreachable host, not a protected one. "
                f"This is an outage misfiled as a policy and it is "
                f"refused at compile time like one (feature 156)."
            )
        hosts[name] = HostPolicy(
            name=name, role=role, ingress=ingress, egress=egress
        )

    return ZonePolicy(zone=zone, hosts=hosts)


def _parse_rules(
    raw: Any, what: str, *, endpoints: str = "sources"
) -> tuple[IngressRule, ...]:
    """Parse an ingress/egress rule list, holding both to one shape.

    Egress reuses :class:`IngressRule`'s shape (a span, a protocol, a
    list of endpoints) because a dial-out allowance and a listen
    allowance differ in *direction* — which half of the host block they
    may appear in, and which of them the live-trading law empties — not
    in grammar.
    """
    if raw is None:
        raise PolicyDocumentError(
            f"{what} is absent. The empty list is the live trading host's "
            f"whole ingress vocabulary, and it must be *written* — a "
            f"compiler that read an absent half as an empty one would be "
            f"turning silence into the strongest promise the document "
            f"makes. 'Absent' and 'forbidden to be anything' are "
            f"different promises, and only the second one is feature "
            f"156's (refused, fail closed)."
        )
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
        raise PolicyDocumentError(
            f"{what} must be a list of rules (empty for none), got "
            f"{raw!r}. The empty list is the live trading host's whole "
            f"ingress vocabulary — a missing or malformed one is refused "
            f"rather than read as empty, because 'absent' and 'forbidden "
            f"to be anything' are different promises (feature 156)."
        )
    return tuple(
        IngressRule.from_document(
            rule, f"{what} rule #{index + 1}", endpoints=endpoints
        )
        for index, rule in enumerate(raw)
    )


def load_zone_policy(path: Path) -> ZonePolicy:
    """Load and compile the zone document at ``path``.

    JSON, read whole and compiled whole — the committed artifact
    (:data:`COMMITTED_ZONE_POLICY`) and any proposed change to it pass
    through the same :func:`compile_zone_policy` refusal, so the
    document on disk cannot drift open without the compile failing.
    """
    with path.open("r", encoding="utf-8") as handle:
        document = json.load(handle)
    return compile_zone_policy(document)


def committed_zone_policy() -> ZonePolicy:
    """The compiled policy of the live trading zone as committed.

    The document this feature stands up: read from
    :data:`COMMITTED_ZONE_POLICY` and compiled through the same law as
    any change to it, so what the gate consults and what the operator
    applied are provably the same surface.
    """
    return load_zone_policy(COMMITTED_ZONE_POLICY)
