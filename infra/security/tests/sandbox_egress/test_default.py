"""Feature 149: the committed default — the artifact the law is checked
against.

"By default" is a posture, and this file's subject is the thing that
makes it checkable: the committed document
(:data:`~infra.security.sandbox_egress.COMMITTED_SANDBOX_EGRESS_POLICY`)
*is* the default — what the deployment runs with before anyone writes a
stanza. The tests here read it the way an operator or a CI check would:
compiled through the same refusal as any change to it, covering the Z1
boxes §3 actually draws, answering an attempt at the lake in the lake's
own words, and refusing to drift open on disk exactly as it refuses in
memory.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from infra.security.sandbox_egress import (
    COMMITTED_SANDBOX_EGRESS_POLICY,
    POLICY_KIND,
    EgressAttempt,
    EgressReason,
    SandboxEgressPolicy,
    SandboxEgressRuleRejected,
    authorize_egress,
    compile_sandbox_egress_policy,
    load_sandbox_egress_policy,
)
from infra.security.tests.sandbox_egress.helpers import (
    DATA_LAKE_ADDRESS,
    DATA_LAKE_NAME,
    LAKE_RULE,
    POLICY_RUNTIME,
    SIGNAL_SANDBOX,
)


class TestTheArtifact:
    """The document on disk, as facts rather than prose."""

    def test_the_artifact_exists_beside_the_module(self) -> None:
        """The committed policy is shipped with the law that checks it,
        so a checkout cannot hold one without the other."""
        assert COMMITTED_SANDBOX_EGRESS_POLICY.exists()

    def test_the_artifact_declares_its_kind(self) -> None:
        """It says what it is — the marker the compile holds it to, so
        a stray JSON file cannot be read as this policy."""
        with COMMITTED_SANDBOX_EGRESS_POLICY.open("r", encoding="utf-8") as handle:
            document = json.load(handle)
        assert document["policy"] == POLICY_KIND

    def test_the_artifact_writes_every_egress_half_empty(self) -> None:
        """The promise, literally written: every sandbox block carries
        an 'egress' key and it is the empty list — 'held empty by law',
        not absent and not silently so."""
        with COMMITTED_SANDBOX_EGRESS_POLICY.open("r", encoding="utf-8") as handle:
            document = json.load(handle)
        assert document["sandboxes"]
        assert all(block["egress"] == [] for block in document["sandboxes"])


class TestTheCommittedDefault:
    """What the compiled artifact holds, and for whom."""

    def test_the_default_compiles_from_disk(
        self, committed: SandboxEgressPolicy
    ) -> None:
        """The loader's whole job, proven: read the committed file,
        refuse nothing about it, hand back a policy."""
        assert committed.kind == POLICY_KIND

    def test_the_default_covers_both_z1_sandboxes(
        self, committed: SandboxEgressPolicy
    ) -> None:
        """§3 draws two sandboxed boxes in Z1 — the signal sandbox and
        the policy runtime — and the committed default covers both:
        membership, so each inherits the empty surface by being
        listed."""
        assert {surface.name for surface in committed.sandboxes()} == {
            SIGNAL_SANDBOX,
            POLICY_RUNTIME,
        }

    def test_the_default_holds_every_surface_empty(
        self, committed: SandboxEgressPolicy
    ) -> None:
        """The inspectable form of 'denies all egress': no sandbox in
        the committed default leaves the compile with an allowance or a
        span."""
        assert all(surface.allowances == () for surface in committed.sandboxes())
        assert all(surface.egress_spans() == () for surface in committed.sandboxes())

    def test_the_default_names_the_lake_and_its_network(
        self, committed: SandboxEgressPolicy
    ) -> None:
        """The asset is named on both spellings: an attempt at the
        name, and an attempt at an address inside the lake's network,
        are both recognized as reaching for it."""
        lake = committed.data_lake
        assert lake.name == DATA_LAKE_NAME
        assert lake.reached_by(DATA_LAKE_NAME)
        assert lake.reached_by(DATA_LAKE_ADDRESS)

    def test_reloading_yields_the_same_emptiness(
        self, committed: SandboxEgressPolicy
    ) -> None:
        """The compile is a function of the document, not of history:
        two reads of the committed artifact hold the same (empty)
        surfaces."""
        again = load_sandbox_egress_policy(COMMITTED_SANDBOX_EGRESS_POLICY)
        assert [s.egress_spans() for s in again.sandboxes()] == [
            s.egress_spans() for s in committed.sandboxes()
        ]


class TestTheDefaultAnswers:
    """The end-to-end sentence, over the artifact as committed."""

    def test_an_attempt_at_the_lake_is_rejected_over_the_committed_default(
        self, committed: SandboxEgressPolicy
    ) -> None:
        """The feature's own words, delivered by the default with
        nothing added to it: the signal sandbox reaches for the lake by
        name and is rejected with the lake's reason."""
        decision = authorize_egress(
            EgressAttempt(origin=SIGNAL_SANDBOX, destination=DATA_LAKE_NAME, port=443),
            committed,
        )
        assert decision.allowed is False
        assert decision.reason is EgressReason.NO_NETWORK_PATH_TO_DATA_LAKE

    def test_the_policy_runtime_is_covered_by_the_same_default(
        self, committed: SandboxEgressPolicy
    ) -> None:
        """The second Z1 box, the same answer — the law keys on
        membership and the membership is written."""
        decision = authorize_egress(
            EgressAttempt(
                origin=POLICY_RUNTIME, destination=DATA_LAKE_NAME, port=5432
            ),
            committed,
        )
        assert decision.reason is EgressReason.NO_NETWORK_PATH_TO_DATA_LAKE

    def test_an_attempt_at_the_lake_by_address_is_rejected_over_the_default(
        self, committed: SandboxEgressPolicy
    ) -> None:
        """The address-shaped attempt over the committed artifact: an
        address inside the lake's network is the lake, recognized by
        containment, rejected in the lake's words."""
        decision = authorize_egress(
            EgressAttempt(
                origin=SIGNAL_SANDBOX, destination=DATA_LAKE_ADDRESS, port=443
            ),
            committed,
        )
        assert decision.reason is EgressReason.NO_NETWORK_PATH_TO_DATA_LAKE


class TestTheDefaultCannotDriftOpen:
    """The document on disk is under the same law as any document in
    memory."""

    def test_a_drifted_copy_on_disk_is_refused_at_load(
        self, tmp_path: Path
    ) -> None:
        """The check an operator's pull request would face: write the
        committed artifact with one egress rule granted, and the loader
        refuses the file — the drift cannot be applied through this
        path, whatever path it takes."""
        with COMMITTED_SANDBOX_EGRESS_POLICY.open("r", encoding="utf-8") as handle:
            document = json.load(handle)
        document["sandboxes"][0]["egress"] = [dict(LAKE_RULE)]
        drifted = tmp_path / "drifted_sandbox_egress_policy.json"
        drifted.write_text(json.dumps(document), encoding="utf-8")
        with pytest.raises(SandboxEgressRuleRejected):
            load_sandbox_egress_policy(drifted)

    def test_the_committed_path_itself_would_refuse_the_drift(self) -> None:
        """The refusal is in the compile, not in this suite's fixtures:
        the same document that loads cleanly from the committed path is
        refused the moment one rule appears in it — proved against the
        module's own constant, not a copy."""
        with COMMITTED_SANDBOX_EGRESS_POLICY.open("r", encoding="utf-8") as handle:
            document = json.load(handle)
        document["sandboxes"][0]["egress"] = [dict(LAKE_RULE)]
        with pytest.raises(SandboxEgressRuleRejected):
            compile_sandbox_egress_policy(document)
