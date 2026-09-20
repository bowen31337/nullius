"""Feature 149: the compile-time law — all egress, refused as one.

The sentence's first claim and the seam that carries it: *System denies
all egress from sandboxes by default.* The deny happens before anything
is applied, at :func:`~infra.security.sandbox_egress.compile_sandbox_egress_policy`,
so the tests here hand the compiler documents a granting edit could
really produce — well-formed, parseable, otherwise lawful — and assert
the whole document is refused, with the drift named.

Three groups, one per contract: the committed default compiles; every
allowance is refused whatever its shape; the grammar is held so the
law's inputs are real, with every failure staying inside this module's
taxonomy.
"""

from __future__ import annotations

import json

import pytest

from infra.security.network_policy import PolicyDocumentError
from infra.security.sandbox_egress import (
    COMMITTED_SANDBOX_EGRESS_POLICY,
    POLICY_KIND,
    EgressPolicyDocumentError,
    MissingDataLake,
    SandboxEgressError,
    SandboxEgressRuleRejected,
    compile_sandbox_egress_policy,
)
from infra.security.tests.sandbox_egress.helpers import (
    DATA_LAKE_NAME,
    DATA_LAKE_NETWORK,
    EVERYWHERE_RULE,
    LAKE_RULE,
    POLICY_RUNTIME,
    SESSION_BROKER,
    SIGNAL_SANDBOX,
    document_with_egress_rule,
    sandbox_policy_document,
)


class TestTheCommittedDefaultCompiles:
    """The posture the deployment runs with, as a checkable fact."""

    def test_the_committed_document_loads_and_compiles(self) -> None:
        """The artifact beside the module is a policy, and the compile
        that enforces the law accepts it — the default is not itself
        drift."""
        with COMMITTED_SANDBOX_EGRESS_POLICY.open("r", encoding="utf-8") as handle:
            document = json.load(handle)
        policy = compile_sandbox_egress_policy(document)
        assert policy.kind == POLICY_KIND

    def test_every_sandbox_compiles_with_an_empty_surface(self) -> None:
        """The law's own output shape: no sandbox leaves the compile
        holding an allowance."""
        policy = compile_sandbox_egress_policy(sandbox_policy_document())
        assert all(surface.allowances == () for surface in policy.sandboxes())

    def test_every_sandbox_compiles_with_no_egress_spans(self) -> None:
        """The inspectable promise: ``()`` is 'denies all egress' as a
        fact a renderer or audit can point at."""
        policy = compile_sandbox_egress_policy(sandbox_policy_document())
        assert all(surface.egress_spans() == () for surface in policy.sandboxes())


class TestTheLawRefusesEveryAllowance:
    """'All' is the claim, so the refusal is total over shapes."""

    def test_a_rule_to_the_data_lake_is_refused(self) -> None:
        """The grant the feature is named for: the lake itself, on the
        port a convenience edit would reach for first."""
        with pytest.raises(SandboxEgressRuleRejected):
            compile_sandbox_egress_policy(document_with_egress_rule(LAKE_RULE))

    def test_a_rule_to_the_lakes_network_is_refused(self) -> None:
        """The same grant in address form — an allowance spelled as a
        CIDR is still an allowance."""
        rule = {"port": 443, "protocol": "tcp", "destinations": [DATA_LAKE_NETWORK]}
        with pytest.raises(SandboxEgressRuleRejected):
            compile_sandbox_egress_policy(document_with_egress_rule(rule))

    def test_a_rule_to_an_external_api_is_refused(self) -> None:
        """The law does not only guard the named asset: an allowance to
        anywhere is refused, because 'all egress' is the claim."""
        rule = {"port": 443, "protocol": "tcp", "destinations": ["exchange-api"]}
        with pytest.raises(SandboxEgressRuleRejected):
            compile_sandbox_egress_policy(document_with_egress_rule(rule))

    def test_a_rule_to_everywhere_is_refused(self) -> None:
        """The widest grant — every port, to 0.0.0.0/0 — is refused like
        the narrowest; if any shape could pass, this one would."""
        with pytest.raises(SandboxEgressRuleRejected):
            compile_sandbox_egress_policy(document_with_egress_rule(EVERYWHERE_RULE))

    def test_a_udp_rule_is_refused(self) -> None:
        """Protocol is not a side door: a UDP grant is drift in a
        different protocol and is refused in the same words."""
        rule = {"port": 53, "protocol": "udp", "destinations": [DATA_LAKE_NAME]}
        with pytest.raises(SandboxEgressRuleRejected):
            compile_sandbox_egress_policy(document_with_egress_rule(rule))

    def test_a_rule_to_the_session_broker_is_refused(self) -> None:
        """The live trading zone earns its broker egress by its own law
        (feature 156); the sandbox earns nothing by proximity — the one
        allowance the trusted zone holds is refused on this side."""
        rule = {"port": 443, "protocol": "tcp", "destinations": [SESSION_BROKER]}
        with pytest.raises(SandboxEgressRuleRejected):
            compile_sandbox_egress_policy(document_with_egress_rule(rule))

    def test_the_law_holds_for_every_sandbox_in_the_list(self) -> None:
        """Membership, not name: the grant on the *second* sandbox is
        refused as firmly as on the first, and a third listed sandbox
        would be covered the moment it was written."""
        with pytest.raises(SandboxEgressRuleRejected):
            compile_sandbox_egress_policy(
                document_with_egress_rule(LAKE_RULE, sandbox=POLICY_RUNTIME)
            )

    def test_the_refusal_names_the_sandbox(self) -> None:
        """The drift is findable: the refusal says which box carries the
        rule an operator must go look at."""
        with pytest.raises(SandboxEgressRuleRejected, match=SIGNAL_SANDBOX):
            compile_sandbox_egress_policy(document_with_egress_rule(LAKE_RULE))

    def test_the_refusal_names_the_rule(self) -> None:
        """...and which rule, in the grammar the document wrote it in —
        protocol, span and destination, spelled as egress ('to')."""
        with pytest.raises(
            SandboxEgressRuleRejected, match=r"tcp/443 to 'data-lake'"
        ):
            compile_sandbox_egress_policy(document_with_egress_rule(LAKE_RULE))

    def test_the_refusal_cites_the_clause(self) -> None:
        """The message is traceable to the sentence: §17's posture is
        quoted back at the drift."""
        with pytest.raises(SandboxEgressRuleRejected, match="by default"):
            compile_sandbox_egress_policy(document_with_egress_rule(LAKE_RULE))

    def test_the_whole_document_is_refused_not_the_rule_skipped(self) -> None:
        """A policy applied with rules silently dropped is one whose
        file and whose sandbox disagree — the compile's whole answer is
        the exception, so there is no partial policy to carry on with."""
        with pytest.raises(SandboxEgressRuleRejected):
            compile_sandbox_egress_policy(document_with_egress_rule(LAKE_RULE))

    def test_the_law_is_repeatable(self) -> None:
        """Refusing is not a state that can be worn down: the same drift
        compiled twice is refused twice."""
        for _ in range(3):
            with pytest.raises(SandboxEgressRuleRejected):
                compile_sandbox_egress_policy(document_with_egress_rule(LAKE_RULE))

    def test_the_refusal_is_a_sandbox_egress_error(self) -> None:
        """So a caller that treats every failure of this law alike
        catches the taxonomy with one ``except``."""
        assert issubclass(SandboxEgressRuleRejected, SandboxEgressError)


class TestTheGrammarIsHeld:
    """'Held empty by law' must be *written* — and the law's inputs must
    be real documents, not guessed-at ones."""

    @pytest.mark.parametrize(
        ("mutate", "expected"),
        [
            pytest.param(
                lambda doc: doc["sandboxes"][0].pop("egress"),
                EgressPolicyDocumentError,
                id="absent-egress-half",
            ),
            pytest.param(
                lambda doc: doc["sandboxes"][0].__setitem__("egress", None),
                EgressPolicyDocumentError,
                id="null-egress-half",
            ),
            pytest.param(
                lambda doc: doc["sandboxes"][0].__setitem__("egress", "[]"),
                EgressPolicyDocumentError,
                id="egress-half-not-a-list",
            ),
            pytest.param(
                lambda doc: doc["sandboxes"][0].pop("name"),
                EgressPolicyDocumentError,
                id="sandbox-without-a-name",
            ),
            pytest.param(
                lambda doc: doc["sandboxes"].append(dict(doc["sandboxes"][0])),
                EgressPolicyDocumentError,
                id="duplicate-sandbox",
            ),
            pytest.param(
                lambda doc: doc.__setitem__("sandboxes", "signal-sandbox"),
                EgressPolicyDocumentError,
                id="sandboxes-not-a-list",
            ),
            pytest.param(
                lambda doc: doc.__setitem__("policy", "zone-policy"),
                EgressPolicyDocumentError,
                id="wrong-policy-marker",
            ),
            pytest.param(
                lambda doc: doc["data_lake"].__setitem__("name", ""),
                EgressPolicyDocumentError,
                id="blank-lake-name",
            ),
            pytest.param(
                lambda doc: doc["data_lake"].__setitem__("addresses", []),
                EgressPolicyDocumentError,
                id="lake-with-no-addresses",
            ),
            pytest.param(
                lambda doc: doc["data_lake"].__setitem__("addresses", ["not-a-cidr"]),
                EgressPolicyDocumentError,
                id="lake-address-not-a-cidr",
            ),
            pytest.param(
                lambda doc: doc["data_lake"].__setitem__("addresses", [23]),
                EgressPolicyDocumentError,
                id="lake-address-not-a-string",
            ),
            pytest.param(
                lambda doc: doc.__setitem__("data_lake", "data-lake"),
                EgressPolicyDocumentError,
                id="lake-block-not-a-mapping",
            ),
        ],
    )
    def test_a_document_that_cannot_be_read_is_refused(
        self, mutate, expected: type[Exception]
    ) -> None:
        """One sweep over the malformed spellings: the compiler fails
        closed on all of them, and each failure names its contract via
        this module's own vocabulary."""
        document = sandbox_policy_document()
        mutate(document)
        with pytest.raises(expected):
            compile_sandbox_egress_policy(document)

    def test_a_document_that_is_not_a_mapping_is_refused(self) -> None:
        """The outermost shape is checked too — a bare list is not a
        policy waiting to be read charitably."""
        with pytest.raises(EgressPolicyDocumentError):
            compile_sandbox_egress_policy(["sandbox-egress"])

    def test_a_policy_that_names_no_lake_is_missing_its_asset(self) -> None:
        """The rejection the feature is named for cannot be given
        without the lake's identity, so a document without it is
        refused as incomplete rather than compiled as vacuous."""
        document = sandbox_policy_document()
        del document["data_lake"]
        with pytest.raises(MissingDataLake):
            compile_sandbox_egress_policy(document)

    def test_an_empty_sandboxes_list_still_compiles(self) -> None:
        """No vacuous-truth trap: a policy covering nothing is a law
        with nobody to cover, not a malformed document — the committed
        default carries the real boxes, and a future zone's list is the
        deployment's to write."""
        document = sandbox_policy_document()
        document["sandboxes"] = []
        policy = compile_sandbox_egress_policy(document)
        assert policy.sandboxes() == ()


class TestErrorsStayInThisTaxonomy:
    """The seam discipline: this module's failures are this module's
    types, so a caller's one ``except`` actually catches them all."""

    @pytest.mark.parametrize(
        "document",
        [
            23,
            {"policy": POLICY_KIND},
            document_with_egress_rule(LAKE_RULE),
            document_with_egress_rule(
                {"port": 443, "port_range": [1, 2], "protocol": "tcp",
                 "destinations": [DATA_LAKE_NAME]},
            ),
        ],
        ids=["not-a-mapping", "no-lake-no-sandboxes", "the-law", "unreadable-rule"],
    )
    def test_every_compile_failure_is_a_sandbox_egress_error(
        self, document
    ) -> None:
        """The taxonomy is one base class wide, whatever contract the
        document broke."""
        with pytest.raises(SandboxEgressError):
            compile_sandbox_egress_policy(document)

    def test_rule_parse_failures_are_translated_not_leaked(self) -> None:
        """The rule grammar is shared with the zone policy
        (``network_policy``), and its parse errors arrive here
        translated: the raised type is this module's, so a caller
        catching the sandbox-egress taxonomy is not defeated by a
        helper raising another feature's error type."""
        drift = document_with_egress_rule(
            {"port": 443, "port_range": [1, 2], "protocol": "tcp",
             "destinations": [DATA_LAKE_NAME]}
        )
        with pytest.raises(EgressPolicyDocumentError) as raised:
            compile_sandbox_egress_policy(drift)
        assert not isinstance(raised.value, PolicyDocumentError)

    def test_the_translated_failure_names_its_cause(self) -> None:
        """The original parse failure rides along as the cause, so an
        operator reading the traceback still sees the shared grammar's
        own words about the rule it could not read."""
        drift = document_with_egress_rule(
            {"port": 443, "port_range": [1, 2], "protocol": "tcp",
             "destinations": [DATA_LAKE_NAME]}
        )
        with pytest.raises(EgressPolicyDocumentError) as raised:
            compile_sandbox_egress_policy(drift)
        assert isinstance(raised.value.__cause__, PolicyDocumentError)

    def test_missing_data_lake_is_a_sandbox_egress_error(self) -> None:
        """The newest member of the taxonomy joins the base."""
        assert issubclass(MissingDataLake, SandboxEgressError)
        assert issubclass(EgressPolicyDocumentError, SandboxEgressError)
