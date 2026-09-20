"""Feature 157: the committed artifact — the posture the law is checked against.

The step this file's subject makes checkable: *"configured without gVisor
isolation"* is only a refusable condition if the deployment has a written-down
statement of what *with* gVisor isolation means.  The committed document
(:data:`~sandbox.isolation.COMMITTED_ISOLATION_POLICY`) *is* that statement —
what the deployment runs with before anyone writes a stanza — and the tests
here read it the way an operator or a CI check would: compiled through the same
refusal as any change to it, covering the Z1 boxes §3 actually draws, naming
gVisor's mechanism and runtime rather than a spelling a reader has to
interpret, and refusing to drift on disk exactly as it refuses in memory.
"""

from __future__ import annotations

import json

from _documents import POLICY_RUNTIME, SIGNAL_SANDBOX
from sandbox import (
    COMMITTED_ISOLATION_POLICY,
    GVISOR_MECHANISM,
    GVISOR_RUNTIME,
    POLICY_KIND,
    committed_isolation_policy,
    load_isolation_policy,
)


class TestTheArtifact:
    """The document on disk, as facts rather than prose."""

    def test_the_artifact_exists_beside_the_module(self) -> None:
        """The committed policy ships with the law that checks it, so a
        checkout cannot hold one without the other."""
        assert COMMITTED_ISOLATION_POLICY.exists()

    def test_the_artifact_declares_its_kind(self) -> None:
        """It says what it is — the marker the compile holds it to, so a
        stray JSON file cannot be read as this policy."""
        with COMMITTED_ISOLATION_POLICY.open("r", encoding="utf-8") as handle:
            document = json.load(handle)
        assert document["policy"] == POLICY_KIND

    def test_the_artifact_writes_an_isolation_block_for_every_component(self) -> None:
        """The promise, literally written: every component carries an
        ``isolation`` block with both halves spelled — 'held to gVisor by
        law', not absent and not silently so."""
        with COMMITTED_ISOLATION_POLICY.open("r", encoding="utf-8") as handle:
            document = json.load(handle)
        assert document["components"]
        for block in document["components"]:
            assert "isolation" in block, block
            assert block["isolation"]["mechanism"] == GVISOR_MECHANISM
            assert block["isolation"]["runtime"] == GVISOR_RUNTIME


class TestTheCommittedPolicy:
    """What the compiled artifact holds, and for whom."""

    def test_the_committed_policy_compiles_from_disk(self) -> None:
        """The loader's whole job, proven: read the committed file, refuse
        nothing about it, hand back a policy."""
        assert committed_isolation_policy().kind == POLICY_KIND

    def test_the_committed_policy_covers_both_z1_boxes(self) -> None:
        """§3 draws two sandboxed boxes in Z1 — the signal sandbox and the
        policy runtime — and feature 157's law is held per component, so a
        policy covering only one would leave the other's runs answered
        UNKNOWN_COMPONENT while the deployment believed it was covered."""
        names = committed_isolation_policy().names()
        assert set(names) == {SIGNAL_SANDBOX, POLICY_RUNTIME}

    def test_every_committed_component_is_gvisor(self) -> None:
        """The artifact's whole claim, read off the compiled object rather
        than the file: no component of this deployment is configured without
        gVisor isolation."""
        policy = committed_isolation_policy()
        assert policy.components()
        for component in policy.components():
            assert component.is_gvisor, component

    def test_the_loader_and_the_committed_shortcut_agree(self) -> None:
        """``committed_isolation_policy`` is not privileged: it goes through
        the same read-and-compile as any other path, so a drift in the file
        is refused on both."""
        assert load_isolation_policy(COMMITTED_ISOLATION_POLICY).names() == (
            committed_isolation_policy().names()
        )

    def test_the_compiled_components_carry_gvisors_spelling(self) -> None:
        """A caller asking *what mechanism is this box on?* reads gVisor's
        own two strings — compiled from the law's constants, never from
        whatever a document happened to capitalize."""
        component = committed_isolation_policy().isolation_of(SIGNAL_SANDBOX)
        assert component is not None
        assert component.mechanism == GVISOR_MECHANISM
        assert component.runtime == GVISOR_RUNTIME
