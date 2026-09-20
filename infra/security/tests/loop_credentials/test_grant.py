"""Feature 148: the compile — a grant that writes the zone never lands.

The law's compile-time half.  The grant document is trusted input — an
operator wrote it, CI checks it — so a document that drifts open is
refused with an exception the caller cannot ignore, the same stance
feature 156's compile holds over ingress and feature 149's over
egress.  What the tests below assert is *which contract* each refusal
names, because the refusal is the audit record: a malformed block is
one thing, and a write onto the immutable zone is the feature's own
law, with its own type and its own words.

The last group holds the contrasts: the read-only grants on zone
members compile, the genuine writes outside the zone compile, and only
the write that would reach the zone — inside it, or covering it — is
refused, whole document, first offender named.
"""

from __future__ import annotations

import pytest

from infra.security.loop_credentials import (
    READ_OPERATIONS,
    WRITE_OPERATIONS,
    CredentialOperation,
    GrantDocumentError,
    LoopCredentialError,
    MissingImmutableZone,
    ZoneWritePermissionRejected,
    compile_loop_credential_policy,
)
from infra.security.tests.loop_credentials.helpers import (
    FILESYSTEM_ROOT,
    POLICY_ROLE,
    POLICY_RUNTIME,
    SIGNAL_ROLE,
    SIGNAL_SANDBOX,
    TRAVERSAL_SIDECAR,
    TRIAL_LEDGER_DB,
    WORK_AREA_POLICY,
    ZONE_CONTRACT,
    ZONE_COST_MODEL,
    ZONE_EVALUATOR,
    ZONE_NAME,
    ZONE_NEIGHBOUR,
    ZONE_NULLORACLE,
    ZONE_PARENT,
    ZONE_PATHS,
    ZONE_SNAPSHOTS,
    ZONE_TRIAL_LEDGER,
    ZONES_ROOT,
    document_with_extra_permission,
    document_with_zone_write,
    document_without_zone,
    grant_document,
)

#: A member's own child, used to pin the zone's members against
#: nesting (a member inside a member adds no place).
SIDECAR_MEMBER: str = ZONE_NULLORACLE + "/sidecar.key"

# ── the vocabulary: closed, and split in exactly two ───────────────────


class TestVocabulary:
    def test_the_sides_partition_the_vocabulary(self) -> None:
        """Read ∪ write is everything; read ∩ write is nothing."""
        reads = set(CredentialOperation.read_vocabulary())
        writes = set(CredentialOperation.write_vocabulary())
        everything = set(CredentialOperation)
        assert reads | writes == everything
        assert not reads & writes

    def test_eleven_named_operations(self) -> None:
        """Three reads, eight writes — the count the docstring claims."""
        assert len(CredentialOperation.read_vocabulary()) == 3
        assert len(CredentialOperation.write_vocabulary()) == 8
        assert len(list(CredentialOperation)) == 11

    @pytest.mark.parametrize("operation", list(CredentialOperation))
    def test_is_write_agrees_with_membership(self, operation) -> None:
        """The property reads the same list the vocabularies hold."""
        assert operation.is_write == (
            operation in CredentialOperation.write_vocabulary()
        )

    @pytest.mark.parametrize(
        ("operation", "expected"),
        [("read", False), ("list", False), ("stat", False)]
        + [(op.value, True) for op in CredentialOperation.write_vocabulary()],
    )
    def test_string_frozensets_match_the_sides(
        self, operation: str, expected: bool
    ) -> None:
        """The gate's string view of the split is the enum's own."""
        assert (operation in WRITE_OPERATIONS) is expected
        assert (operation in READ_OPERATIONS) is not expected

    def test_frozensets_are_the_sides_exactly(self) -> None:
        assert READ_OPERATIONS == frozenset(
            op.value for op in CredentialOperation.read_vocabulary()
        )
        assert WRITE_OPERATIONS == frozenset(
            op.value for op in CredentialOperation.write_vocabulary()
        )


# ── the document: what it must say about itself ─────────────────────────


class TestDocumentShape:
    def test_the_baseline_grant_compiles(self) -> None:
        """The suite's starting point is itself lawful."""
        policy = compile_loop_credential_policy(grant_document())
        assert policy.kind == "loop-credentials"
        assert [c.name for c in policy.components()] == [
            SIGNAL_SANDBOX,
            POLICY_RUNTIME,
        ]

    def test_a_non_mapping_document_is_refused(self) -> None:
        with pytest.raises(GrantDocumentError, match="must be a mapping"):
            compile_loop_credential_policy(["not", "a", "mapping"])

    def test_an_absent_kind_is_refused(self) -> None:
        with pytest.raises(GrantDocumentError, match="non-empty string"):
            compile_loop_credential_policy(
                {"immutable_zone": {}, "components": []}
            )

    def test_a_document_of_the_wrong_kind_is_refused(self) -> None:
        with pytest.raises(GrantDocumentError, match="zone-policy"):
            compile_loop_credential_policy(
                {"policy": "zone-policy", "components": []}
            )

    def test_absent_components_is_refused(self) -> None:
        document = grant_document()
        del document["components"]
        with pytest.raises(
            GrantDocumentError, match="'components' is absent"
        ):
            compile_loop_credential_policy(document)

    def test_non_list_components_is_refused(self) -> None:
        document = grant_document()
        document["components"] = SIGNAL_SANDBOX
        with pytest.raises(GrantDocumentError, match="must be a list"):
            compile_loop_credential_policy(document)


# ── the zone block: the place the law is named for ──────────────────────


class TestZoneBlock:
    def test_absent_zone_is_missing_immutable_zone(self) -> None:
        """A grant that cannot say which paths are the zone could never
        recognize the write it must refuse."""
        with pytest.raises(MissingImmutableZone):
            compile_loop_credential_policy(document_without_zone())

    def test_missing_zone_is_the_taxonomys_own_type(self) -> None:
        assert issubclass(MissingImmutableZone, LoopCredentialError)

    def test_empty_zone_paths_are_refused(self) -> None:
        document = grant_document()
        document["immutable_zone"]["paths"] = []
        with pytest.raises(
            GrantDocumentError, match="non-empty list of rooted paths"
        ):
            compile_loop_credential_policy(document)

    @pytest.mark.parametrize(
        "path", ["zones/z0", "relative", "", "//zones/z0", 7, None]
    )
    def test_paths_that_are_not_canonical_absolute_are_refused(
        self, path
    ) -> None:
        document = grant_document()
        document["immutable_zone"]["paths"] = [path]
        with pytest.raises(GrantDocumentError):
            compile_loop_credential_policy(document)

    def test_the_whole_filesystem_is_not_a_zone(self) -> None:
        document = grant_document()
        document["immutable_zone"]["paths"] = [FILESYSTEM_ROOT]
        with pytest.raises(
            GrantDocumentError, match="whole filesystem the zone"
        ):
            compile_loop_credential_policy(document)

    def test_a_duplicate_member_is_refused(self) -> None:
        document = grant_document()
        document["immutable_zone"]["paths"].append(ZONE_SNAPSHOTS)
        with pytest.raises(GrantDocumentError, match="paths pin"):
            compile_loop_credential_policy(document)

    def test_a_duplicate_under_another_spelling_is_refused(self) -> None:
        """A trailing slash is the same place after normalization."""
        document = grant_document()
        document["immutable_zone"]["paths"].append(
            ZONE_TRIAL_LEDGER + "/"
        )
        with pytest.raises(GrantDocumentError, match="pin"):
            compile_loop_credential_policy(document)

    def test_a_member_inside_a_member_is_refused(self) -> None:
        """The zone is a union of roots, not à la carte."""
        document = grant_document()
        document["immutable_zone"]["paths"].append(SIDECAR_MEMBER)
        with pytest.raises(GrantDocumentError, match="one inside the other"):
            compile_loop_credential_policy(document)

    def test_the_zone_name_must_be_written(self) -> None:
        document = grant_document()
        document["immutable_zone"]["name"] = ""
        with pytest.raises(GrantDocumentError, match="non-empty string"):
            compile_loop_credential_policy(document)


# ── components, credentials, permissions: the set's own shape ──────────


class TestSetShape:
    def test_a_duplicate_component_is_refused(self) -> None:
        document = grant_document()
        document["components"].append(document["components"][0])
        with pytest.raises(GrantDocumentError, match="described twice"):
            compile_loop_credential_policy(document)

    def test_absent_credentials_are_refused_not_read_as_empty(self) -> None:
        """"Absent" and "held empty on purpose" are different promises."""
        document = grant_document()
        del document["components"][0]["credentials"]
        with pytest.raises(
            GrantDocumentError, match="'credentials' is absent"
        ):
            compile_loop_credential_policy(document)

    def test_an_explicitly_empty_credential_set_compiles(self) -> None:
        """A component granted nothing rejects every zone write
        vacuously — a legal shape, but one the document must write."""
        document = grant_document()
        document["components"][0]["credentials"] = []
        policy = compile_loop_credential_policy(document)
        assert policy.component(SIGNAL_SANDBOX).credentials == ()
        assert policy.component(SIGNAL_SANDBOX).write_targets() == ()

    def test_absent_permissions_are_refused(self) -> None:
        document = grant_document()
        del document["components"][0]["credentials"][0]["permissions"]
        with pytest.raises(
            GrantDocumentError, match="'permissions' is absent"
        ):
            compile_loop_credential_policy(document)

    def test_a_duplicate_credential_name_is_refused(self) -> None:
        document = grant_document()
        component = document["components"][0]
        component["credentials"].append(component["credentials"][0])
        with pytest.raises(GrantDocumentError, match="appears twice"):
            compile_loop_credential_policy(document)

    def test_a_permission_with_no_operations_is_refused(self) -> None:
        document = document_with_extra_permission(
            {"path": WORK_AREA_POLICY, "operations": []}
        )
        with pytest.raises(
            GrantDocumentError, match="non-empty list"
        ):
            compile_loop_credential_policy(document)

    @pytest.mark.parametrize(
        "operations", ["write", 7, None, {"write": True}]
    )
    def test_non_list_operations_are_refused(self, operations) -> None:
        document = document_with_extra_permission(
            {"path": WORK_AREA_POLICY, "operations": operations}
        )
        with pytest.raises(GrantDocumentError):
            compile_loop_credential_policy(document)

    @pytest.mark.parametrize(
        "operation", ["Write", "w", "overwrite", "truncate+write"]
    )
    def test_unknown_operations_are_refused_never_dropped(
        self, operation: str
    ) -> None:
        """A misspelled write must not read as a compliant grant."""
        document = document_with_zone_write(WORK_AREA_POLICY, [operation])
        with pytest.raises(
            GrantDocumentError, match="not of the credential vocabulary"
        ):
            compile_loop_credential_policy(document)

    def test_a_relative_permission_path_is_refused(self) -> None:
        document = document_with_zone_write("work/out.py", ["write"])
        with pytest.raises(GrantDocumentError, match="absolute path"):
            compile_loop_credential_policy(document)

    def test_permission_paths_are_pinned_canonical(self) -> None:
        """A trailing slash collapses before the set is trusted."""
        document = document_with_zone_write(
            WORK_AREA_POLICY + "/", ["write"]
        )
        policy = compile_loop_credential_policy(document)
        assert (
            WORK_AREA_POLICY
            in policy.component(SIGNAL_SANDBOX).write_targets()
        )


# ── the law: no write onto the zone, any way round ─────────────────────


class TestTheLaw:
    @pytest.mark.parametrize(
        "operation",
        [op.value for op in CredentialOperation.write_vocabulary()],
    )
    def test_every_write_operation_onto_a_zone_path_is_refused(
        self, operation: str
    ) -> None:
        """All eight, from write to chown — 'every write' enumerates."""
        document = document_with_zone_write(
            TRIAL_LEDGER_DB, [operation]
        )
        with pytest.raises(ZoneWritePermissionRejected):
            compile_loop_credential_policy(document)

    @pytest.mark.parametrize("zone_path", list(ZONE_PATHS))
    def test_every_zone_member_refuses_a_write(self, zone_path: str) -> None:
        document = document_with_zone_write(zone_path, ["append"])
        with pytest.raises(ZoneWritePermissionRejected):
            compile_loop_credential_policy(document)

    @pytest.mark.parametrize(
        "path",
        [
            ZONE_TRIAL_LEDGER,
            TRIAL_LEDGER_DB,
            TRAVERSAL_SIDECAR,
            ZONE_TRIAL_LEDGER + "/",
        ],
    )
    def test_every_spelling_of_a_zone_place_is_refused(
        self, path: str
    ) -> None:
        """Deep, exact, traversal-shaped, trailing-slashed — the place
        is the place after normalization."""
        document = document_with_zone_write(path, ["write"])
        with pytest.raises(ZoneWritePermissionRejected):
            compile_loop_credential_policy(document)

    @pytest.mark.parametrize(
        "covering", [ZONE_PARENT, ZONES_ROOT, FILESYSTEM_ROOT]
    )
    def test_a_covering_grant_is_a_write_in_disguise(
        self, covering: str
    ) -> None:
        """A capability on the parent reaches every child of it."""
        document = document_with_zone_write(covering, ["write"])
        with pytest.raises(
            ZoneWritePermissionRejected, match="in disguise"
        ):
            compile_loop_credential_policy(document)

    def test_a_neighbour_is_not_the_zone(self) -> None:
        """/zones/z0-sidecar shares a prefix, not a segment."""
        policy = compile_loop_credential_policy(
            document_with_zone_write(ZONE_NEIGHBOUR, ["write"])
        )
        assert ZONE_NEIGHBOUR in policy.component(
            SIGNAL_SANDBOX
        ).write_targets()

    def test_read_only_grants_on_zone_members_compile(self) -> None:
        policy = compile_loop_credential_policy(
            document_with_extra_permission(
                {"path": ZONE_NULLORACLE, "operations": ["read", "stat"]}
            )
        )
        assert policy.component(SIGNAL_SANDBOX).permits(
            ZONE_NULLORACLE, "read"
        )

    def test_a_mixed_permission_still_refuses(self) -> None:
        """The read halves do not launder the write half."""
        document = document_with_zone_write(
            ZONE_SNAPSHOTS, ["read", "list", "write"]
        )
        with pytest.raises(ZoneWritePermissionRejected):
            compile_loop_credential_policy(document)

    @pytest.mark.parametrize(
        ("component", "credential"),
        [(SIGNAL_SANDBOX, SIGNAL_ROLE), (POLICY_RUNTIME, POLICY_ROLE)],
    )
    def test_the_law_holds_for_every_component(
        self, component: str, credential: str
    ) -> None:
        """Membership is how a component inherits the law — being
        listed is what earns the refusal."""
        document = document_with_zone_write(
            ZONE_COST_MODEL, ["chmod"],
            component=component, credential=credential,
        )
        with pytest.raises(ZoneWritePermissionRejected):
            compile_loop_credential_policy(document)

    def test_the_refusal_names_the_offender(self) -> None:
        document = document_with_zone_write(
            ZONE_EVALUATOR, ["rename"],
        )
        with pytest.raises(
            ZoneWritePermissionRejected, match="signal-sandbox"
        ) as caught:
            compile_loop_credential_policy(document)
        message = str(caught.value)
        assert "signal-sandbox-role" in message
        assert ZONE_EVALUATOR in message
        assert "'rename'" in message
        assert ZONE_NAME in message

    def test_the_whole_document_is_refused_not_the_permission(self) -> None:
        """First offender in document order; nothing after compiles."""
        document = document_with_zone_write(ZONE_SNAPSHOTS, ["write"])
        document["components"][0]["credentials"][0]["permissions"].append(
            {"path": ZONE_EVALUATOR, "operations": ["delete"]}
        )
        with pytest.raises(
            ZoneWritePermissionRejected, match="'write'"
        ) as caught:
            compile_loop_credential_policy(document)
        assert ZONE_SNAPSHOTS in str(caught.value)


# ── the contrasts: what the lawful grant does hold ──────────────────────


class TestTheContrasts:
    def test_genuine_writes_outside_the_zone_compile(self) -> None:
        policy = compile_loop_credential_policy(grant_document())
        signal = policy.component(SIGNAL_SANDBOX)
        assert signal.write_targets() == (
            "/zones/z1/signal-sandbox/work",
            "/zones/z3/artifacts/signal",
        )

    def test_the_commissioning_read_grant_compiles(self) -> None:
        """The policy runtime reads the contract member — read is not
        the feature's subject, writes are."""
        policy = compile_loop_credential_policy(grant_document())
        assert policy.component(POLICY_RUNTIME).permits(
            ZONE_CONTRACT, "list"
        )
