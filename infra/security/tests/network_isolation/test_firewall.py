"""The applied artifact: the emptiness survives all the way to the render.

app_spec.xml, "Trust Zone Isolation & Secrets", feature 156 — the
"because no inbound port is exposed" half, at the far end of the
chain.  The compiler refusing a document is a promise about a
*document*; what an operator actually applies is the rendered
security group, and a promise that stopped one step short of it would
be a law nothing enforced.  These tests close the chain: document →
compile → render, with no step that could widen the live trading
host's empty ingress surface.

The artifact is the one place the feature's claim is checkable rather
than arguable.  "No inbound port is exposed" is ``IpPermissions == []``
on the live host's rendered group — an object an applier reads, not a
sentence an author wrote.
"""

from __future__ import annotations

import json

import pytest

from infra.security import (
    COMMITTED_ZONE_POLICY,
    LIVE_TRADING_ROLE,
    IngressRuleRejected,
    compile_zone_policy,
    exposed_inbound_ports,
    render_security_group,
    render_zone_security_groups,
)


class TestTheLiveHostRendersEmpty:
    """The whole feature, in one assertion an applier would make."""

    def test_live_host_has_no_inbound_permissions(self, live_zone) -> None:
        rendered = render_zone_security_groups(live_zone)
        live = rendered["live-trading-1"]
        assert live["IpPermissions"] == []
        assert live["Role"] == LIVE_TRADING_ROLE

    def test_exposed_inbound_ports_is_the_empty_tuple(self, live_zone) -> None:
        host = live_zone.host("live-trading-1")
        assert host is not None
        assert exposed_inbound_ports(host) == ()

    def test_the_bastion_beside_it_still_has_its_door(self, live_zone) -> None:
        """§17 in two tuples: the front door open, the live host sealed.

        Without this contrast a renderer that printed ``[]`` for
        *every* host would pass the test above while having quietly
        abolished the zone's only way in.
        """
        rendered = render_zone_security_groups(live_zone)
        assert len(rendered["bastion-1"]["IpPermissions"]) == 1
        bastion = rendered["bastion-1"]["IpPermissions"][0]
        assert bastion["FromPort"] == 22
        assert bastion["ToPort"] == 22
        assert bastion["IpRanges"] == [{"CidrIp": "10.20.0.0/24"}]


class TestTheAsymmetry:
    """Empty in, open out — the shape that makes sessions necessary."""

    def test_live_host_keeps_its_egress(self, live_zone) -> None:
        """Empty ingress with no egress would be an outage, not a law."""
        rendered = render_zone_security_groups(live_zone)
        egress = rendered["live-trading-1"]["IpPermissionsEgress"]
        assert egress, "a live host with no dial-out path is unreachable"
        destinations = [
            ref for rule in egress for ref in rule["DestinationRefs"]
        ]
        assert "session-broker" in destinations

    def test_egress_renders_under_the_destination_key(
        self, live_zone
    ) -> None:
        """Direction is carried by the key, so the two never blur."""
        rendered = render_zone_security_groups(live_zone)
        for rule in rendered["live-trading-1"]["IpPermissionsEgress"]:
            assert "DestinationRefs" in rule
            assert "SourceRefs" not in rule

    def test_inbound_renders_under_the_source_key(self, live_zone) -> None:
        rendered = render_zone_security_groups(live_zone)
        rule = rendered["bastion-1"]["IpPermissions"][0]
        assert "SourceRefs" in rule
        assert "DestinationRefs" not in rule
        assert rule["IpRanges"] == [{"CidrIp": "10.20.0.0/24"}]


class TestTheChainCannotWiden:
    """No step between the document and the artifact adds a port."""

    def test_a_drifted_document_never_reaches_the_renderer(self) -> None:
        """The compile is the choke point, and it is upstream of the render.

        A document opening a live host cannot produce an artifact at
        all: the refusal happens before anything is rendered, so there
        is no ordering in which a widened surface gets applied and the
        error surfaced afterwards.
        """
        raw = json.loads(COMMITTED_ZONE_POLICY.read_text(encoding="utf-8"))
        host = next(h for h in raw["hosts"] if h["role"] == LIVE_TRADING_ROLE)
        host["ingress"].append(
            {"port": 22, "protocol": "tcp", "sources": ["bastion-1"]}
        )
        with pytest.raises(IngressRuleRejected):
            compile_zone_policy(raw)

    def test_a_second_live_host_also_renders_empty(self) -> None:
        """The renderer holds no per-host special case — the role carries it."""
        document = {
            "zone": "live-trading",
            "hosts": [
                {
                    "name": "live-trading-2",
                    "role": LIVE_TRADING_ROLE,
                    "ingress": [],
                    "egress": [
                        {
                            "port": 443,
                            "protocol": "tcp",
                            "destinations": ["session-broker"],
                        }
                    ],
                }
            ],
        }
        policy = compile_zone_policy(document)
        rendered = render_zone_security_groups(policy)
        assert rendered["live-trading-2"]["IpPermissions"] == []

    def test_render_is_pure_and_repeatable(self, live_zone) -> None:
        """Same compiled policy in, same artifact out — no hidden state."""
        assert render_zone_security_groups(
            live_zone
        ) == render_zone_security_groups(live_zone)

    def test_every_rule_in_the_artifact_carries_a_port(self, live_zone) -> None:
        """A rendered rule with no span would be an open port by omission.

        Every span in the artifact must trace to a rule the compiler
        parsed and range-checked — there is no "all ports" spelling a
        renderer could emit for a rule that never named one.
        """
        for group in render_zone_security_groups(live_zone).values():
            for rule in group["IpPermissions"]:
                assert 1 <= rule["FromPort"] <= rule["ToPort"] <= 65535


class TestTheSingleHostRender:
    """``render_security_group`` carries its own audit header."""

    def test_header_names_zone_host_and_role(self, live_zone) -> None:
        host = live_zone.host("live-trading-1")
        assert host is not None
        rendered = render_security_group(host, zone=live_zone.zone)
        assert rendered["Zone"] == "live-trading"
        assert rendered["Host"] == "live-trading-1"
        assert rendered["Role"] == LIVE_TRADING_ROLE

    def test_header_matches_the_zone_bulk_render(self, live_zone) -> None:
        """The per-host and per-zone spellings agree, host for host."""
        host = live_zone.host("bastion-1")
        assert host is not None
        assert render_security_group(host, zone=live_zone.zone) == (
            render_zone_security_groups(live_zone)["bastion-1"]
        )
