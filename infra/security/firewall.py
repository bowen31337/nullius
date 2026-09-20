"""The applied artifact: rendering the law into what gets enforced.

app_spec.xml, "Trust Zone Isolation & Secrets", feature 156: *System
rejects access to the live trading host that does not arrive through a
bastion session, because no inbound port is exposed.*  The gate
(:mod:`infra.security.host_access`) answers arrivals; this module
prints the surface those answers cite, in the shape an infrastructure
renderer would apply — one security-group-style document per host,
inbound permissions and outbound permissions, so the claim "no inbound
port is exposed" can be checked against the artifact rather than taken
from the prose.

The rendering is deliberately cloud-agnostic — the security-group
vocabulary (``IpPermissions`` / ``IpPermissionsEgress``, CIDR ranges)
is close enough to universal that the rendered document reads the same
to whichever layer applies it, and nothing here dials an API.  What it
guarantees is the shape, and the shape is the point:

* **the live trading host renders with empty ``IpPermissions``.**  Not
  a narrowed list, not an allowlist — an empty one.  The renderer
  prints what the compiled policy holds
  (:class:`infra.security.network_policy.ZonePolicy`), and the
  compiler refuses any document in which a live-trading host holds an
  ingress rule, so an applied artifact with a live-host inbound
  permission cannot be produced from a compilable document.  The
  emptiness travels: document → compile → render, with no step that
  could widen it.

* **egress renders open where the host needs it.**  The live trading
  host's outbound half names the exchange endpoints and the session
  broker — the dial-out path its bastion sessions ride.  The asymmetry
  visible in one artifact (empty in, open out) *is* §17's topology:
  nothing can start a connection to this host; it starts them all.

* **the bastion renders its one rule.**  SSH from the operator
  allowlist — the front door the zone keeps so the empty live-host
  surface is a scoped law, not a sealed building.

Stdlib-only, pure: a renderer, not an applier — applying is the
operator's step, and it starts from the artifact this prints.
"""

from __future__ import annotations

from typing import Any

from .network_policy import (
    HostPolicy,
    IngressRule,
    ZonePolicy,
)

__all__ = [
    "exposed_inbound_ports",
    "render_security_group",
    "render_zone_security_groups",
]


def _render_rule(rule: IngressRule, endpoints_key: str) -> dict[str, Any]:
    """One rule in the applied vocabulary: protocol, span, endpoint lists."""
    lo, hi = rule.port_range
    cidrs: list[dict[str, str]] = []
    refs: list[str] = []
    for endpoint in rule.sources:
        # A CIDR goes to IpRanges, the vocabulary every applier reads; a
        # host name goes to a refs list, the vocabulary a zone-internal
        # renderer resolves. Neither is widened on the way through.
        if "/" in endpoint:
            cidrs.append({"CidrIp": endpoint})
        else:
            refs.append(endpoint)
    rendered: dict[str, Any] = {
        "IpProtocol": rule.protocol,
        "FromPort": lo,
        "ToPort": hi,
        endpoints_key: refs,
    }
    if cidrs:
        rendered["IpRanges"] = cidrs
    return rendered


def render_security_group(host: HostPolicy, *, zone: str) -> dict[str, Any]:
    """One host's applied surface: empty inbound for a live-trading host.

    The output is the document an applier would enforce — inbound
    ``IpPermissions`` and outbound ``IpPermissionsEgress``, plus the
    zone/host/role header that makes the artifact auditable against
    the committed zone document it was rendered from.
    """
    return {
        "Zone": zone,
        "Host": host.name,
        "Role": host.role,
        "IpPermissions": [
            _render_rule(rule, "SourceRefs") for rule in host.ingress
        ],
        "IpPermissionsEgress": [
            _render_rule(rule, "DestinationRefs") for rule in host.egress
        ],
    }


def render_zone_security_groups(policy: ZonePolicy) -> dict[str, dict[str, Any]]:
    """The whole zone's applied surfaces, keyed by host name.

    Rendering the committed policy through this and checking the
    live-trading hosts' ``IpPermissions == []`` is the end-to-end form
    of the feature's "because": the artifact that gets applied exposes
    no inbound port on the live trading host, so an arrival that did
    not ride a bastion session finds nothing to arrive at.
    """
    return {
        host.name: render_security_group(host, zone=policy.zone)
        for host in policy.hosts()
    }


def exposed_inbound_ports(host: HostPolicy) -> tuple[tuple[int, int], ...]:
    """The inbound port spans ``render_security_group`` would open.

    The inspectable promise itself: ``()`` for a live-trading host
    (:data:`infra.security.network_policy.LIVE_TRADING_ROLE` is the
    law's key, and the compiler holds every host carrying it empty),
    the written spans for any other host — the bastion's ``((22, 22),)``
    beside the live host's ``()`` is §17 in two tuples.
    """
    return host.inbound_spans()
