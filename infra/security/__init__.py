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
modules, and seven have:

* :mod:`infra.security.key_backup` — feature 155's *two independent
  stores*, the sealed sidecar-key backup and the reconciliation
  between the stores.
* :mod:`infra.security.audit_log` — feature 154's *access audit
  record per read of the null sidecar key*, the append-only chained
  log and the chokepoint that writes to it before serving a key.
* :mod:`infra.security.credential_isolation` — feature 153's
  *separate credentials per environment*, the binding that classifies
  a key by the environment the exchange stamped into it.
* :mod:`infra.security.exchange_keys` — feature 152's *trade
  permission with withdrawal permanently disabled*, the permission
  set a provisioned key may carry, the account-side switch, and the
  validation that refuses every other shape.
* :mod:`infra.security.secrets_manager` — feature 151's *credentials
  in a secrets manager*, the store contract that keeps a credential
  out of committed environment files.
* :mod:`infra.security.provider_boundary` — feature 150's *provider
  API call outside the sandbox*, the zone-stamped call whose client
  refuses the sandbox's side, and the conduit that sends code in and
  takes code out.
* :mod:`infra.security.sandbox_egress` — feature 149's *all egress
  from sandboxes denied by default*, the compile that refuses a
  sandbox any egress allowance and the gate that answers every
  attempt — one at the data lake with the lake's own reason,
  everything else with the default's.

The exports below are feature 156's alone, deliberately: this module's
``__all__`` is the zone-policy vocabulary, and a caller reaching for
the audit log or the backup names its own submodule
(``from infra.security.audit_log import AuditLog``) rather than
finding it here beside the zone's gate.  One namespace per feature
keeps the gate's ``Channel`` from sitting next to an unrelated
``Channel`` a later member grows — the discipline feature 150's
:class:`~infra.security.provider_boundary.CodeChannel` is the most
recent instance of, and the reason it is not re-exported here beside
the gate's ``Channel``.
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
