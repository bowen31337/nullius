"""The law itself: no ingress rule survives compile on a live host.

app_spec.xml, "Trust Zone Isolation & Secrets", feature 156 — the
"because no inbound port is exposed" half.  These tests hold the
compiler to the sentence's absoluteness: not "narrow ingress", not
"ingress from the bastion", not "ingress on the admin port" — *no
inbound port*, for every host carrying the live-trading role, in
every spelling a drift could be written in, with the whole document
refused rather than the rule skipped.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from infra.security import (
    COMMITTED_ZONE_POLICY,
    LIVE_TRADING_ROLE,
    IngressRuleRejected,
    MissingBrokerEgress,
    PolicyDocumentError,
    compile_zone_policy,
    load_zone_policy,
)


def _live_zone_document(ingress: list, egress: list | None = None) -> dict:
    """A minimal zone with one live-trading host, ingress as given.

    ``egress`` defaults to the broker-reachable shape the corollary
    demands, so a test pins one thing at a time.
    """
    return {
        "zone": "live-trading",
        "hosts": [
            {
                "name": "live-trading-1",
                "role": LIVE_TRADING_ROLE,
                "ingress": ingress,
                "egress": egress
                if egress is not None
                else [
                    {
                        "port": 443,
                        "protocol": "tcp",
                        "destinations": ["session-broker"],
                    }
                ],
            }
        ],
    }


class TestCommittedDocument:
    """The artifact as shipped compiles, and compiles empty."""

    def test_committed_document_compiles(self) -> None:
        policy = load_zone_policy(COMMITTED_ZONE_POLICY)
        assert policy.zone == "live-trading"
        assert [host.name for host in policy.hosts()] == [
            "bastion-1",
            "live-trading-1",
        ]

    def test_committed_document_is_json_on_disk(self) -> None:
        raw = json.loads(COMMITTED_ZONE_POLICY.read_text(encoding="utf-8"))
        assert isinstance(raw, dict)

    def test_live_trading_host_has_no_inbound_port(self, live_zone) -> None:
        host = live_zone.host("live-trading-1")
        assert host is not None
        assert host.role == LIVE_TRADING_ROLE
        assert host.ingress == ()
        assert host.inbound_spans() == ()

    def test_every_live_trading_host_is_empty(self, live_zone) -> None:
        """The law keys on the role, so a second live host inherits it."""
        live = live_zone.live_trading_hosts()
        assert len(live) >= 1
        assert all(host.inbound_spans() == () for host in live)

    def test_zone_has_a_bastion_with_its_one_rule(self, live_zone) -> None:
        """The contrast that scopes the law: the bastion keeps a front door."""
        bastion = live_zone.host("bastion-1")
        assert bastion is not None
        assert bastion.inbound_spans() == ((22, 22),)

    def test_live_host_can_still_dial_the_broker(self, live_zone) -> None:
        """Empty ingress with no outbound path would be an outage, not a law."""
        host = live_zone.host("live-trading-1")
        assert host is not None
        assert any(
            "session-broker" in rule.sources for rule in host.egress
        )


class TestTheLaw:
    """Any ingress rule on a live-trading host refuses the document."""

    @pytest.mark.parametrize(
        ("port", "protocol"),
        [(22, "tcp"), (443, "tcp"), (3389, "tcp"), (9092, "tcp"), (53, "udp")],
    )
    def test_single_port_rule_is_rejected(
        self, port: int, protocol: str
    ) -> None:
        document = _live_zone_document(
            [
                {
                    "port": port,
                    "protocol": protocol,
                    "sources": ["0.0.0.0/0"],
                }
            ]
        )
        with pytest.raises(IngressRuleRejected) as caught:
            compile_zone_policy(document)
        assert "live-trading-1" in str(caught.value)
        assert str(port) in str(caught.value)

    def test_port_range_rule_is_rejected(self) -> None:
        """'Open 30000-40000' is one rule, and one refusal."""
        document = _live_zone_document(
            [
                {
                    "port_range": [30000, 40000],
                    "protocol": "tcp",
                    "sources": ["10.20.0.0/24"],
                }
            ]
        )
        with pytest.raises(IngressRuleRejected, match="30000-40000"):
            compile_zone_policy(document)

    def test_bastion_source_is_not_an_exemption(self) -> None:
        """The drift the law exists for: 'SSH from the bastion only'."""
        document = _live_zone_document(
            [{"port": 22, "protocol": "tcp", "sources": ["bastion-1"]}]
        )
        with pytest.raises(IngressRuleRejected) as caught:
            compile_zone_policy(document)
        message = str(caught.value)
        assert "bastion" in message.lower()

    def test_operator_allowlist_is_not_an_exemption(self) -> None:
        document = _live_zone_document(
            [{"port": 22, "protocol": "tcp", "sources": ["10.20.0.0/24"]}]
        )
        with pytest.raises(IngressRuleRejected):
            compile_zone_policy(document)

    def test_second_live_host_is_covered_too(self) -> None:
        """A zone with two live hosts refuses the second one's rule."""
        document = _live_zone_document([])
        document["hosts"].append(
            {
                "name": "live-trading-2",
                "role": LIVE_TRADING_ROLE,
                "ingress": [
                    {"port": 22, "protocol": "tcp", "sources": ["bastion-1"]}
                ],
                "egress": [
                    {
                        "port": 443,
                        "protocol": "tcp",
                        "destinations": ["session-broker"],
                    }
                ],
            }
        )
        with pytest.raises(IngressRuleRejected, match="live-trading-2"):
            compile_zone_policy(document)

    def test_rule_after_a_clean_host_is_still_found(self) -> None:
        """Order is not a hiding place: a clean first host changes nothing."""
        document = _live_zone_document(
            [{"port": 22, "protocol": "tcp", "sources": ["bastion-1"]}]
        )
        clean_bastion = {
            "name": "bastion-1",
            "role": "bastion",
            "ingress": [
                {"port": 22, "protocol": "tcp", "sources": ["10.20.0.0/24"]}
            ],
            "egress": [],
        }
        document["hosts"].insert(0, clean_bastion)
        with pytest.raises(IngressRuleRejected):
            compile_zone_policy(document)

    def test_committed_document_cannot_drift_open_in_memory(self) -> None:
        """The end-to-end drift story: mutate the shipped document open."""
        raw = json.loads(COMMITTED_ZONE_POLICY.read_text(encoding="utf-8"))
        host = next(
            h for h in raw["hosts"] if h["role"] == LIVE_TRADING_ROLE
        )
        host["ingress"].append(
            {"port": 22, "protocol": "tcp", "sources": ["bastion-1"]}
        )
        with pytest.raises(IngressRuleRejected):
            compile_zone_policy(raw)


class TestTheCorollary:
    """A live host must keep the outbound path its sessions ride."""

    def test_no_broker_egress_is_rejected(self) -> None:
        document = _live_zone_document(
            [],
            egress=[
                {"port": 443, "protocol": "tcp", "destinations": ["exchange-api"]}
            ],
        )
        with pytest.raises(MissingBrokerEgress):
            compile_zone_policy(document)

    def test_empty_egress_is_rejected(self) -> None:
        with pytest.raises(MissingBrokerEgress):
            compile_zone_policy(_live_zone_document([], egress=[]))

    def test_broker_egress_via_a_span_still_counts(self) -> None:
        """The path matters, not the spelling it was granted in."""
        document = _live_zone_document(
            [],
            egress=[
                {
                    "port_range": [1024, 65535],
                    "protocol": "tcp",
                    "destinations": ["session-broker"],
                }
            ],
        )
        policy = compile_zone_policy(document)
        host = policy.host("live-trading-1")
        assert host is not None
        assert host.inbound_spans() == ()


class TestFailClosed:
    """A document the compiler cannot read completely, it will not trust."""

    @pytest.mark.parametrize(
        "mangle",
        [
            lambda d: d.__setitem__("hosts", "not-a-list"),
            lambda d: d["hosts"].__setitem__(0, "not-a-mapping"),
            lambda d: d["hosts"][0].__setitem__("name", ""),
            lambda d: d["hosts"][0].pop("role"),
            lambda d: d["hosts"].append(dict(d["hosts"][0])),
            lambda d: d["hosts"][0].__setitem__(
                "ingress",
                [{"protocol": "tcp", "sources": ["0.0.0.0/0"]}],
            ),
            lambda d: d["hosts"][0].__setitem__(
                "ingress",
                [{"port": 22, "port_range": [1, 2], "protocol": "tcp",
                  "sources": ["0.0.0.0/0"]}],
            ),
            lambda d: d["hosts"][0].__setitem__(
                "ingress",
                [{"port": 0, "protocol": "tcp", "sources": ["0.0.0.0/0"]}],
            ),
            lambda d: d["hosts"][0].__setitem__(
                "ingress",
                [{"port": 22, "protocol": "tcp", "sources": []}],
            ),
        ],
    )
    def test_malformed_documents_are_refused(self, mangle) -> None:
        document = _live_zone_document([])
        mangle(document)
        with pytest.raises(PolicyDocumentError):
            compile_zone_policy(document)

    def test_missing_ingress_key_is_refused_not_read_as_empty(self) -> None:
        """'Absent' and 'forbidden to be anything' are different promises."""
        document = _live_zone_document([])
        document["hosts"][0].pop("ingress")
        with pytest.raises(PolicyDocumentError):
            compile_zone_policy(document)

    def test_not_a_mapping_at_all(self) -> None:
        with pytest.raises(PolicyDocumentError):
            compile_zone_policy(["not", "a", "mapping"])

    def test_missing_file_is_an_error(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            load_zone_policy(tmp_path / "absent.json")
