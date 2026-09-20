"""Feature 148: the committed artifact — the set the system grants.

The "by default" of this feature is not a posture someone remembers;
it is a file.  ``loop_credential_policy.json`` is the credential set
the system grants the loop's components, and the tests below read it
through the same compile as any change to it would face, so what they
assert holds of the artifact an operator applies, not of a dict a test
assembled.

The headline group is the round trip: take the committed document off
the disk, put a write onto the zone in it, and watch the compile
refuse its own artifact — the file cannot drift open without the
compile failing, which is the whole reason the law lives at compile
time rather than in review.
"""

from __future__ import annotations

import copy
import json

import pytest

from infra.security.loop_credentials import (
    COMMITTED_LOOP_CREDENTIAL_POLICY,
    POLICY_KIND,
    READ_OPERATIONS,
    ZoneWritePermissionRejected,
    compile_loop_credential_policy,
)
from infra.security.tests.loop_credentials.helpers import (
    POLICY_ROLE,
    POLICY_RUNTIME,
    SIGNAL_SANDBOX,
    ZONE_NAME,
    ZONE_PATHS,
    ZONE_TRIAL_LEDGER,
)

# The committed artifact, as raw JSON — the round-trip group's starting
# point, so the drift they inject is drift into the real file's shape,
# not into the suite's in-memory baseline.
_committed_document: dict = json.loads(
    COMMITTED_LOOP_CREDENTIAL_POLICY.read_text(encoding="utf-8")
)


class TestTheArtifact:
    def test_the_artifact_is_named_for_whose_credentials_it_holds(
        self,
    ) -> None:
        assert COMMITTED_LOOP_CREDENTIAL_POLICY.name == (
            "loop_credential_policy.json"
        )

    def test_the_artifact_declares_its_kind(self) -> None:
        assert _committed_document["policy"] == POLICY_KIND

    def test_the_artifact_compiles(self, committed) -> None:
        assert committed.kind == POLICY_KIND

    def test_the_zone_is_pinned_by_its_members(self, committed) -> None:
        """The six roots are §2's Z0 contents, in document order."""
        assert committed.immutable_zone.name == ZONE_NAME
        assert committed.immutable_zone.paths == ZONE_PATHS


class TestMembership:
    def test_both_loop_mutated_components_are_listed(self, committed) -> None:
        """§3's component map draws exactly these two Z1 boxes — the
        same membership feature 149's committed policy carries."""
        assert [c.name for c in committed.components()] == [
            SIGNAL_SANDBOX,
            POLICY_RUNTIME,
        ]

    def test_an_unlisted_component_holds_nothing(self, committed) -> None:
        assert committed.component("policy-dev-agent") is None

    def test_each_component_holds_a_named_credential(self, committed) -> None:
        for component in committed.components():
            assert component.credentials
            assert all(
                credential.permissions for credential in component.credentials
            )


class TestTheGrantIsReal:
    """The set is deliberately full, not empty — that is what makes the
    law a law rather than an emptiness."""

    def test_every_component_can_truly_write_somewhere(self, committed) -> None:
        for component in committed.components():
            assert component.write_targets()

    @pytest.mark.parametrize(
        "component_name", [SIGNAL_SANDBOX, POLICY_RUNTIME]
    )
    def test_no_write_target_is_inside_the_zone(
        self, committed, component_name: str
    ) -> None:
        """The grant's own promise, checkable against the compiled set:
        real write capabilities, all of them outside the zone."""
        zone = committed.immutable_zone
        component = committed.component(component_name)
        for target in component.write_targets():
            assert not zone.covers(target)

    def test_the_work_areas_and_artifact_drops_are_the_targets(
        self, committed
    ) -> None:
        assert committed.component(SIGNAL_SANDBOX).write_targets() == (
            "/zones/z1/signal-sandbox/work",
            "/zones/z3/artifacts/signal",
        )
        assert committed.component(POLICY_RUNTIME).write_targets() == (
            "/zones/z1/policy-runtime/work",
            "/zones/z3/artifacts/policy",
        )


class TestTheZoneHalf:
    def test_the_signal_sandbox_holds_nothing_on_the_zone(
        self, committed
    ) -> None:
        """§1 P4 keeps it fed by pre-sliced payload, never by mount —
        its set holds no permission that covers any zone path at all."""
        zone = committed.immutable_zone
        signal = committed.component(SIGNAL_SANDBOX)
        for credential in signal.credentials:
            for permission in credential.permissions:
                assert not zone.covers(permission.path)

    def test_the_policy_runtime_holds_read_only_zone_grants(
        self, committed
    ) -> None:
        """Read is not the feature's subject; the read-only grants are
        the demonstration that the law is about writes alone."""
        zone = committed.immutable_zone
        policy_runtime = committed.component(POLICY_RUNTIME)
        zone_permissions = [
            permission
            for credential in policy_runtime.credentials
            for permission in credential.permissions
            if zone.covers(permission.path)
        ]
        assert zone_permissions
        for permission in zone_permissions:
            assert permission.operations <= READ_OPERATIONS

    def test_no_credential_writes_the_zone_either_way_round(
        self, committed
    ) -> None:
        """Inside and covering: no write-carrying permission touches a
        zone path, and none sits above one."""
        zone = committed.immutable_zone
        for component in committed.components():
            for credential in component.credentials:
                for permission in credential.permissions:
                    if not permission.write_operations():
                        continue
                    for root in zone.paths:
                        assert not (
                            permission.path == root
                            or permission.path.startswith(root + "/")
                            or root.startswith(permission.path + "/")
                        )


class TestTheRoundTrip:
    """The artifact cannot drift open without the compile failing."""

    @staticmethod
    def _committed_with_zone_write(
        path: str, operations: list[str]
    ) -> dict:
        document = copy.deepcopy(_committed_document)
        document["components"][0]["credentials"][0]["permissions"].append(
            {"path": path, "operations": operations}
        )
        return document

    def test_a_zone_write_into_the_committed_document_is_refused(
        self,
    ) -> None:
        document = self._committed_with_zone_write(
            ZONE_TRIAL_LEDGER, ["append"]
        )
        with pytest.raises(ZoneWritePermissionRejected):
            compile_loop_credential_policy(document)

    def test_a_covering_write_into_the_committed_document_is_refused(
        self,
    ) -> None:
        document = self._committed_with_zone_write("/zones/z0", ["write"])
        with pytest.raises(ZoneWritePermissionRejected):
            compile_loop_credential_policy(document)

    def test_the_other_components_credential_is_refused_too(self) -> None:
        document = copy.deepcopy(_committed_document)
        policy_runtime = document["components"][1]
        assert policy_runtime["name"] == POLICY_RUNTIME
        policy_runtime["credentials"][0]["permissions"].append(
            {"path": "/zones/z0/cost-model/fees.yaml", "operations": ["write"]}
        )
        with pytest.raises(ZoneWritePermissionRejected):
            compile_loop_credential_policy(document)

    def test_the_committed_policy_role_is_named_by_the_refusal(self) -> None:
        document = copy.deepcopy(_committed_document)
        document["components"][1]["credentials"][0]["permissions"].append(
            {"path": "/zones/z0/nulloracle", "operations": ["delete"]}
        )
        with pytest.raises(
            ZoneWritePermissionRejected, match=POLICY_ROLE
        ):
            compile_loop_credential_policy(document)

    def test_the_artifact_on_disk_is_still_the_lawful_one(
        self, committed
    ) -> None:
        """The refusals above never wrote anything back: the committed
        document recompiles clean, every time it is asked."""
        recompiled = compile_loop_credential_policy(_committed_document)
        assert recompiled.kind == committed.kind
        assert (
            recompiled.immutable_zone.paths
            == committed.immutable_zone.paths
        )
        assert [c.name for c in recompiled.components()] == [
            c.name for c in committed.components()
        ]
