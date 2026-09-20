"""Feature 157: the compile — a policy that is not gVisor's is refused.

The sentence's first tense, at the seam a *configuration* is written:
*System rejects a run of agent-authored code configured without gVisor
isolation.*  A policy document is written by trusted code — an operator, a
deployment manifest, a CI check recompiling the artifact — so a document that
would run untrusted code under another mechanism is refused with an exception
the caller cannot ignore, and the whole document is refused rather than the
offending component skipped: a policy applied with a component silently
dropped is one whose file and whose sandbox disagree, and that disagreement is
where the next drift lives.

Two halves are checked and both matter.  The *mechanism* is §5.2's isolation
row; the *runtime* is the OCI runtime shipped with it, and it is the half a
deployment is most likely to get wrong while still believing it is sandboxed
(a container run by ``runc`` is a container).  A law that checked only one
would admit every near-miss, so the drift tests below vary them independently.
"""

from __future__ import annotations

import json

import pytest
from _documents import (
    DEFAULT_OCI_RUNTIME,
    MICROVM_MECHANISM,
    POLICY_RUNTIME,
    SIGNAL_SANDBOX,
    committed_document,
    document_with_mechanism,
    document_with_runtime,
    document_without_isolation,
    isolation_block,
    isolation_document,
)
from sandbox import (
    ISOLATION_REQUIRED_CODE,
    GVisorIsolationRequired,
    IsolationDocumentError,
    compile_isolation_policy,
    load_isolation_policy,
)


class TestCompliantDocuments:
    """The documents the compiler admits, and what it hands back."""

    def test_a_compliant_document_compiles(self) -> None:
        """The base case, so the refusals below are refusals of drift rather
        than refusals of everything."""
        policy = compile_isolation_policy(committed_document())
        assert policy.names() == (SIGNAL_SANDBOX, POLICY_RUNTIME)

    def test_the_components_come_back_in_document_order(self) -> None:
        """Order is the document's, so a reader auditing the compiled policy
        against the file sees the same list."""
        document = isolation_document(
            (POLICY_RUNTIME, isolation_block()),
            (SIGNAL_SANDBOX, isolation_block()),
        )
        assert compile_isolation_policy(document).names() == (
            POLICY_RUNTIME,
            SIGNAL_SANDBOX,
        )

    def test_case_is_not_the_law(self) -> None:
        """``gVisor``/``Runsc`` is the same deployment written by two people;
        a law that refused a capitalization would be a law about typography
        rather than about isolation."""
        document = isolation_document(
            (SIGNAL_SANDBOX, isolation_block(mechanism="gVisor", runtime="Runsc"))
        )
        assert compile_isolation_policy(document).names() == (SIGNAL_SANDBOX,)

    def test_whitespace_is_not_the_law(self) -> None:
        """The same reading, one step further: a padded value is the same
        value."""
        document = isolation_document(
            (SIGNAL_SANDBOX, isolation_block(mechanism=" gvisor ", runtime="runsc "))
        )
        assert compile_isolation_policy(document).names() == (SIGNAL_SANDBOX,)


class TestTheLaw:
    """A document that would run untrusted code without gVisor."""

    def test_a_default_oci_runtime_is_refused(self) -> None:
        """The near-miss that matters most: Docker's default runtime.  The
        box *is* a container and nothing about it looks wrong — which is
        exactly why the runtime is checked beside the mechanism."""
        with pytest.raises(GVisorIsolationRequired):
            compile_isolation_policy(document_with_runtime(DEFAULT_OCI_RUNTIME))

    def test_a_microvm_mechanism_is_refused(self) -> None:
        """§5.2's table names Firecracker as the *alternative* isolation and
        §18 chose gVisor for this deployment, so a document that drifted to
        the other mechanism is refused rather than read as equally good."""
        with pytest.raises(GVisorIsolationRequired):
            compile_isolation_policy(document_with_mechanism(MICROVM_MECHANISM))

    def test_the_refusal_carries_the_features_own_code(self) -> None:
        """Greppable by the feature's own words, so an operator reading a log
        finds the rejection by the thing that was refused."""
        with pytest.raises(GVisorIsolationRequired) as raised:
            compile_isolation_policy(document_with_runtime(DEFAULT_OCI_RUNTIME))
        assert str(raised.value).startswith(ISOLATION_REQUIRED_CODE)

    def test_the_refusal_names_both_halves_of_the_drift(self) -> None:
        """A message that said only 'isolation refused' would hide which of
        the two a drifted configuration got wrong."""
        with pytest.raises(GVisorIsolationRequired) as raised:
            compile_isolation_policy(document_with_runtime(DEFAULT_OCI_RUNTIME))
        message = str(raised.value)
        assert DEFAULT_OCI_RUNTIME in message
        assert "gvisor" in message

    def test_the_refusal_names_the_offending_component(self) -> None:
        """So the drift is findable in a document holding many components."""
        with pytest.raises(GVisorIsolationRequired) as raised:
            compile_isolation_policy(
                document_with_runtime(DEFAULT_OCI_RUNTIME, component=POLICY_RUNTIME)
            )
        assert POLICY_RUNTIME in str(raised.value)

    def test_one_bad_component_refuses_the_whole_document(self) -> None:
        """The whole-document stance, asserted rather than assumed: the
        compliant component does not survive a document whose other half
        drifted — because a policy applied with a component silently dropped
        is one whose file and whose sandbox disagree."""
        with pytest.raises(GVisorIsolationRequired):
            compile_isolation_policy(
                document_with_runtime(DEFAULT_OCI_RUNTIME, component=POLICY_RUNTIME)
            )


class TestDocumentsThatCannotBeRead:
    """Failures of *reading*, kept apart from failures of *the law*."""

    def test_an_absent_isolation_block_is_refused(self) -> None:
        """'Absent' and 'held to gVisor by law' are different promises, and
        only the second is feature 157's — silence must not read as the
        strongest promise the document makes."""
        with pytest.raises(IsolationDocumentError):
            compile_isolation_policy(document_without_isolation())

    def test_a_document_that_does_not_declare_itself_is_refused(self) -> None:
        """A stray JSON file carrying a 'components' key is not this policy."""
        with pytest.raises(IsolationDocumentError):
            compile_isolation_policy({"components": []})

    def test_the_wrong_marker_is_refused(self) -> None:
        """A document that says it is *another* policy is still not this
        one — the marker is compared, not merely present."""
        document = committed_document()
        document["policy"] = "sandbox-egress"
        with pytest.raises(IsolationDocumentError):
            compile_isolation_policy(document)

    def test_a_non_mapping_document_is_refused(self) -> None:
        """A compiler that guessed at the meaning of a stray list would be
        writing policy rather than reading it."""
        with pytest.raises(IsolationDocumentError):
            compile_isolation_policy(["gvisor"])

    def test_a_blank_runtime_is_refused(self) -> None:
        """'Unnamed' is not 'gVisor's': a blank value cannot be held to
        anything, so it is refused as a document failure rather than read as
        a compliant default."""
        with pytest.raises(IsolationDocumentError):
            compile_isolation_policy(
                document_with_runtime(" ", component=SIGNAL_SANDBOX)
            )

    def test_a_non_string_mechanism_is_refused(self) -> None:
        """The same reading for a value of the wrong type entirely."""
        document = committed_document()
        document["components"][0]["isolation"] = {"mechanism": 7, "runtime": "runsc"}
        with pytest.raises(IsolationDocumentError):
            compile_isolation_policy(document)

    def test_a_duplicate_component_is_refused(self) -> None:
        """Two blocks with one name is one component described twice, and the
        applied policy would be whichever came last — drift with extra
        steps."""
        document = isolation_document(
            (SIGNAL_SANDBOX, isolation_block()),
            (SIGNAL_SANDBOX, isolation_block()),
        )
        with pytest.raises(IsolationDocumentError):
            compile_isolation_policy(document)

    def test_an_unnamed_component_is_refused(self) -> None:
        """A component with no name cannot be looked up, so the run that
        claimed it could never be held to anything."""
        document = {"policy": "sandbox-isolation", "components": [{"isolation": isolation_block()}]}
        with pytest.raises(IsolationDocumentError):
            compile_isolation_policy(document)

    def test_a_components_half_that_is_not_a_list_is_refused(self) -> None:
        """The law's whole subject is the boxes; a document that cannot
        enumerate them cannot be compiled."""
        document = {"policy": "sandbox-isolation", "components": {"a": {}}}
        with pytest.raises(IsolationDocumentError):
            compile_isolation_policy(document)

    def test_a_policy_listing_no_components_is_refused(self) -> None:
        """A policy that vouches for nothing would answer every run
        UNKNOWN_COMPONENT while claiming to be the law."""
        with pytest.raises(IsolationDocumentError):
            compile_isolation_policy({"policy": "sandbox-isolation", "components": []})

    def test_the_document_error_is_not_the_law_error(self) -> None:
        """The split is the point: a caller can tell 'nobody can read this
        document' from 'this document named the wrong isolation'.  The second
        is the feature working; the first is the feature unable to say what
        it found.

        Checked by *shape* rather than by class identity, because the two are
        siblings under :class:`SandboxIsolationError` — the distinction is
        that the law's error is :class:`GVisorIsolationRequired` and the
        document's is not, so a caller catching the former never catches the
        latter.
        """
        with pytest.raises(IsolationDocumentError) as raised:
            compile_isolation_policy(document_without_isolation())
        assert not isinstance(raised.value, GVisorIsolationRequired)


class TestReadingFromDisk:
    """A drift written to disk is refused exactly as one compiled in memory."""

    def test_a_missing_file_is_refused(self, tmp_path) -> None:
        """An unreadable policy is not a policy that admits nothing
        gracefully — it is one whose deployment has no law at all."""
        with pytest.raises(IsolationDocumentError):
            load_isolation_policy(tmp_path / "absent.json")

    def test_a_malformed_file_is_refused(self, tmp_path) -> None:
        """Refused rather than read partially."""
        path = tmp_path / "broken.json"
        path.write_text("{not json", encoding="utf-8")
        with pytest.raises(IsolationDocumentError):
            load_isolation_policy(path)

    def test_a_drifted_file_is_refused_by_the_same_law(self, tmp_path) -> None:
        """The load path is not privileged: the file is compiled through the
        identical refusal, so a drift cannot arrive by being written down."""
        path = tmp_path / "drift.json"
        path.write_text(
            json.dumps(document_with_runtime(DEFAULT_OCI_RUNTIME)), encoding="utf-8"
        )
        with pytest.raises(GVisorIsolationRequired):
            load_isolation_policy(path)
