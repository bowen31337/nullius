"""Infrastructure security for the nullius trust zones.

``infra/security/`` is the "Trust Zone Isolation & Secrets" category's
corner of the repository (app_spec.xml): the declarative policy and
policy-time tooling that stand between the zones the architecture
draws (docs/nullius-tech-architecture.md §2) and the infrastructure
they run on.  It is deliberately *not* a uv-workspace member and not a
composition participant — the module loader discovers
``packages/*`` members, and policy that guards the zones must not be
importable code from inside them, so this tree sits outside the
application's own import graph by construction.

This package's subject is app_spec.xml feature 156: *System rejects
access to the live trading host that does not arrive through a bastion
session, because no inbound port is exposed* (§17: "No inbound ports
on the live trading host.  Access via bastion or session manager
only.").  The sentence lands as four modules, one per claim:

* :mod:`infra.security.network_policy` — the law.  The zone document
  (:data:`infra.security.network_policy.COMMITTED_ZONE_POLICY`,
  ``live_trading_zone_policy.json``) and its compiler, which refuses —
  fail closed — any document giving a live-trading host *any* ingress
  rule, and any live-trading host that cannot still dial the session
  broker outbound.
* :mod:`infra.security.bastion` — the carve-out's mechanism.  The
  session broker: hosts register channels by dialing *out*, operators
  attach to what registered, and the session id the broker issues is
  the only capability an arrival can present.
* :mod:`infra.security.host_access` — the gate.  Every arrival is
  answered: a live bastion session to the named destination is
  admitted; everything else is rejected, a direct arrival at the live
  trading host with
  :attr:`~infra.security.host_access.AccessReason.NO_INBOUND_PORT_EXPOSED`
  — the sentence's own "because", cited because the compiled surface
  it consults is empty.
* :mod:`infra.security.firewall` — the applied artifact.  The
  security-group rendering an operator applies, whose live-host
  ``IpPermissions`` is ``[]`` by the same law, so the emptiness
  travels from document to compile to artifact with no step that
  could widen it.

The category's other features join this tree as siblings of these
modules, and two have:

* :mod:`infra.security.key_backup` — feature 155's *two independent
  stores*, the sealed sidecar-key backup and the reconciliation
  between the stores.
* :mod:`infra.security.audit_log` — feature 154's *access audit
  record per read of the null sidecar key*, the append-only chained
  log and the chokepoint that writes to it before serving a key.

The exports below are feature 156's alone, deliberately: this module's
``__all__`` is the zone-policy vocabulary, and a caller reaching for
the audit log or the backup names its own submodule
(``from infra.security.audit_log import AuditLog``) rather than
finding it here beside the zone's gate.  One namespace per feature
keeps the gate's ``Channel`` from sitting next to an unrelated
``Channel`` a later member grows.
"""

from __future__ import annotations

from .bastion import BastionSession, BastionSessionError, SessionBroker, UnknownChannelError
from .firewall import exposed_inbound_ports, render_security_group, render_zone_security_groups
from .host_access import (
    AccessDecision,
    AccessReason,
    AccessRequest,
    Channel,
    authorize_access,
)
from .network_policy import (
    BASTION_ROLE,
    COMMITTED_ZONE_POLICY,
    LIVE_TRADING_ROLE,
    SESSION_BROKER_DESTINATION,
    IngressRule,
    IngressRuleRejected,
    MissingBrokerEgress,
    PolicyDocumentError,
    ZonePolicy,
    ZonePolicyError,
    committed_zone_policy,
    compile_zone_policy,
    load_zone_policy,
)

__all__ = [
    "AccessDecision",
    "AccessReason",
    "AccessRequest",
    "BASTION_ROLE",
    "BastionSession",
    "BastionSessionError",
    "Channel",
    "COMMITTED_ZONE_POLICY",
    "IngressRule",
    "IngressRuleRejected",
    "LIVE_TRADING_ROLE",
    "MissingBrokerEgress",
    "PolicyDocumentError",
    "SESSION_BROKER_DESTINATION",
    "SessionBroker",
    "UnknownChannelError",
    "ZonePolicy",
    "ZonePolicyError",
    "authorize_access",
    "committed_zone_policy",
    "compile_zone_policy",
    "exposed_inbound_ports",
    "load_zone_policy",
    "render_security_group",
    "render_zone_security_groups",
]
