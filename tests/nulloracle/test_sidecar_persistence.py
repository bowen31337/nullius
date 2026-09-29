"""Feature 109, end to end: the assembled system persists null assignments.

app_spec.xml, "Null Oracle & Planted Nulls", feature 109: *System persists
null assignments in an AES-GCM encrypted sidecar file readable by exactly
one service account.*

The member's own suite (``packages/nulloracle/tests``) pins each contract in
isolation — the schema, the cipher, the file, the key.  This suite pins the
sentence those contracts are *for*, through the assembled system: the
sidecar composed by the application factory, read through ``create_app().get``,
resolved from the environment a deployment actually sets, sealing
a campaign's assignments and reading them back.

That distinction matters here more than for most features.  §7.1's file is
the only place in the system a node's null status is written down — *"There
is no is_null column anywhere in the tree store. Not hidden, not nulled out,
not SELECT-excluded. Absent."* — so the integration question is not "does
sealing work" but "does the *composed* system produce a real, sealed,
owner-only sidecar at the location a deployment names, and can it read it
back".  A member that passed its unit suite while the composed application
carried no sidecar at all would satisfy every test below except these.
"""

from __future__ import annotations

import os
import pwd
import stat
import uuid

import pytest

from app.module_loader import create_app

from nulloracle import SERVICE_ACCOUNT_ENV

COMPONENT_NAME = "nulloracle"


def assignment(node_id: str, **overrides) -> dict:
    """The fields of one assignment, as the schema spells them."""
    fields = {"node_id": node_id, "is_null": True, "perm_seed": 11}
    fields.update(overrides)
    return fields


@pytest.fixture
def composed_sidecar(sidecar_path, key_ref: str):
    """The sidecar the *composed application* carries for this environment.

    Read out of the application the factory builds — not constructed
    directly — because the claim under test is about the assembled system:
    a deployment sets two environment variables and the composed application
    must carry a usable sidecar at the path they name.
    """
    return create_app().get(COMPONENT_NAME)


class TestTheComposedSystemCarriesTheSidecar:
    def test_the_factory_composes_a_sidecar_for_the_environment(
        self, composed_sidecar, sidecar_path
    ) -> None:
        assert composed_sidecar is not None
        assert composed_sidecar.path == sidecar_path

    def test_a_fresh_composition_reaches_the_same_sidecar(
        self, sidecar_path, key_ref: str
    ) -> None:
        # ``create_app().get`` is how the rest of this category's features
        # reach the labels, so it must resolve to the sidecar at the path the
        # deployment named.
        assert create_app().get(COMPONENT_NAME).path == sidecar_path

    def test_an_unconfigured_deployment_composes_no_sidecar(self) -> None:
        # Degrade, don't break: an absent sidecar is a discoverable state,
        # and one member's unset variable must not take composition down for
        # every other feature in the workspace.
        app = create_app()
        assert app.get(COMPONENT_NAME) is None
        assert len(app.order) > 5  # ...and the rest of the workspace is there


class TestTheSidecarIsPersistedAndSealed:
    def test_a_campaigns_assignments_round_trip_through_the_composed_system(
        self, composed_sidecar, node_ids
    ) -> None:
        from nulloracle import NullAssignment

        first, second, third = node_ids(3)
        composed_sidecar.write(
            [
                NullAssignment(**assignment(first, is_null=True, perm_seed=1)),
                NullAssignment(**assignment(second, is_null=False, perm_seed=0)),
                NullAssignment(**assignment(third, is_null=True, perm_seed=9, block_days=5)),
            ]
        )
        stored = composed_sidecar.open()
        assert set(stored) == {first, second, third}
        assert stored[first].is_null is True
        assert stored[second].is_null is False
        # Feature 115's reproducibility: the permutation parameters are in
        # the file, not re-derived at read time.
        assert stored[third].perm_seed == 9
        assert stored[third].block_days == 5

    def test_the_file_on_disk_is_a_sealed_container_not_the_plaintext(
        self, composed_sidecar, node_id
    ) -> None:
        from nulloracle import MAGIC, NullAssignment

        composed_sidecar.write([NullAssignment(**assignment(node_id))])
        blob = composed_sidecar.path.read_bytes()
        assert blob.startswith(MAGIC)
        # None of §7.1's schema — nor the node's identity — is readable.
        for token in (b"is_null", b"perm_seed", node_id.encode()):
            assert token not in blob

    def test_the_sidecar_is_owner_only_on_disk(self, composed_sidecar, node_id) -> None:
        from nulloracle import NullAssignment

        composed_sidecar.write([NullAssignment(**assignment(node_id))])
        file_mode = stat.S_IMODE(os.stat(composed_sidecar.path).st_mode)
        dir_mode = stat.S_IMODE(os.stat(composed_sidecar.path.parent).st_mode)
        assert file_mode == 0o600
        assert dir_mode == 0o700

    def test_a_deployment_that_cannot_read_the_key_is_refused_rather_than_served_empty(
        self, composed_sidecar, node_id, raised_named
    ) -> None:
        # The failure §7's table calls unrecoverable.  The system must not
        # answer "no node is null" — that would hand a caller a world where
        # every planted null looks real, and the FDR that followed would be
        # computed over nothing.
        from nulloracle import NullAssignment, SidecarKey

        composed_sidecar.write([NullAssignment(**assignment(node_id))])
        wrong_key = SidecarKey.from_hex("1e" * 32)
        other = type(composed_sidecar)(composed_sidecar.path, wrong_key)
        with raised_named("SidecarDecryptionError"):
            other.open()

    def test_an_altered_sidecar_is_refused(
        self, composed_sidecar, node_id, raised_named
    ) -> None:
        from nulloracle import NullAssignment

        composed_sidecar.write([NullAssignment(**assignment(node_id))])
        raw = bytearray(composed_sidecar.path.read_bytes())
        raw[-1] ^= 0x01
        composed_sidecar.path.write_bytes(bytes(raw))
        with raised_named("SidecarDecryptionError"):
            composed_sidecar.open()


class TestTheBitsAreTheOnlyEnforcement:
    """§1: *"Enforce with filesystem permissions and network policy, never
    with prompt instructions. A prompt is not a security boundary."*

    The composition tests above prove the bits are *set*; these prove they
    are *relied upon* — a loosened sidecar is refused rather than read, so
    the permission is the boundary and not a decoration on one.
    """

    def test_a_loosened_sidecar_is_refused_by_the_composed_system(
        self, composed_sidecar, node_id, raised_named
    ) -> None:
        from nulloracle import NullAssignment

        composed_sidecar.write([NullAssignment(**assignment(node_id))])
        os.chmod(composed_sidecar.path, 0o640)
        with raised_named("SidecarAccessError"):
            composed_sidecar.open()

    def test_the_refusal_survives_a_reread_of_the_same_handle(
        self, composed_sidecar, node_id, raised_named
    ) -> None:
        # The sidecar holds no cache, so tightening the file back is enough
        # to make it readable again — which is what "the bits are the
        # boundary" means: the handle is not a grant.
        from nulloracle import NullAssignment

        composed_sidecar.write([NullAssignment(**assignment(node_id))])
        os.chmod(composed_sidecar.path, 0o644)
        with raised_named("SidecarAccessError"):
            composed_sidecar.open()
        os.chmod(composed_sidecar.path, 0o600)
        assert composed_sidecar.open()[node_id].is_null is True


class TestReadableByExactlyOneServiceAccount:
    """The third clause of feature 109, through the composed system.

    The member suite pins the account rule in isolation.  What is asserted
    here is that a *deployment* naming an account changes what the composed
    sidecar does — that the variable reaches the component the factory built
    and gates a real read, rather than being configuration the member reads
    into a field nobody consults.
    """

    def test_the_composed_sidecar_carries_the_account_the_deployment_names(
        self, composed_sidecar, monkeypatch
    ) -> None:
        # Naming an account must reach the handle the factory returns.
        owner = pwd.getpwuid(os.getuid()).pw_name
        monkeypatch.setenv(SERVICE_ACCOUNT_ENV, owner)
        assert create_app().get(COMPONENT_NAME).account == owner

    def test_the_granted_account_reads_the_sidecar(
        self, composed_sidecar, node_id, monkeypatch
    ) -> None:
        # The positive half, with an account actually named — otherwise the
        # refusal below would pass just as well for a sidecar that refuses
        # everyone, which is not what §7.1 asks for.
        from nulloracle import NullAssignment

        owner = pwd.getpwuid(os.getuid()).pw_name
        composed_sidecar.write([NullAssignment(**assignment(node_id))])
        monkeypatch.setenv(SERVICE_ACCOUNT_ENV, owner)
        granted = create_app().get(COMPONENT_NAME)
        assert granted.account == owner
        assert granted.open()[node_id].is_null is True

    def test_a_foreign_account_is_refused_by_the_composed_system(
        self, composed_sidecar, node_id, monkeypatch, raised_named
    ) -> None:
        # The file has correct bits but belongs to someone else — the copy
        # that kept its 0o600 and lost its owner.  Mode bits alone cannot
        # catch this, so the deployment's named account is what does.
        from nulloracle import NullAssignment

        composed_sidecar.write([NullAssignment(**assignment(node_id))])
        monkeypatch.setenv(SERVICE_ACCOUNT_ENV, "svc-not-the-owner")
        foreign = create_app().get(COMPONENT_NAME)
        assert foreign.account == "svc-not-the-owner"
        with raised_named("SidecarAccessError"):
            foreign.open()

    def test_mode_bits_remain_the_enforcement_when_no_account_is_named(
        self, composed_sidecar, node_id, raised_named
    ) -> None:
        # An unnamed account is a supported deployment state (the
        # single-machine allowance), and it must not become a way to skip
        # the check that actually holds: the mode bits still refuse a
        # loosened file.
        from nulloracle import NullAssignment

        assert composed_sidecar.account is None
        composed_sidecar.write([NullAssignment(**assignment(node_id))])
        os.chmod(composed_sidecar.path, 0o640)
        with raised_named("SidecarAccessError"):
            composed_sidecar.open()


class TestTheTreeStoreNeverLearnsTheBit:
    """Feature 110's rule, from this feature's side.

    app_spec.xml feature 110: *System keeps is_null absent from the tree store
    entirely, which rejects any proposed node column named is_null.*  That
    feature owns the tree-store half; what this suite can assert is the
    consequence that makes it coherent — the *only* place the system writes
    the bit is the sealed file, so a strict reading of the sidecar's own
    contents must not appear in the plaintext of anything else this member
    writes.
    """

    def test_the_bit_appears_in_no_plaintext_artifact_this_member_writes(
        self, composed_sidecar, node_id
    ) -> None:
        from nulloracle import NullAssignment

        composed_sidecar.write([NullAssignment(**assignment(node_id))])
        # Every file this member wrote, read raw.
        written = [
            entry
            for entry in composed_sidecar.path.parent.iterdir()
            if entry.is_file()
        ]
        assert written == [composed_sidecar.path]
        for entry in written:
            assert b"is_null" not in entry.read_bytes()


class TestTheDigestAnswersWithoutTheKey:
    def test_two_seals_of_the_declared_world_are_comparable_without_the_key(
        self, composed_sidecar, node_ids
    ) -> None:
        # The narrow purpose of assignments_digest: a process that may not
        # hold the key can still answer "is this the same sidecar?".  It
        # detects a *different* sidecar and not a *forged* one — only the tag
        # does that — and this test keeps the two claims apart by comparing a
        # declared world against itself and against a different one.
        from nulloracle import NullAssignment, assignments_digest

        first, second = node_ids(2)
        world = [NullAssignment(**assignment(first)), NullAssignment(**assignment(second))]
        assert assignments_digest(world) == assignments_digest(list(world))
        other = [NullAssignment(**assignment(first, is_null=False))]
        assert assignments_digest(world) != assignments_digest(other)

    def test_the_declared_world_is_recoverable_from_the_sealed_file(
        self, composed_sidecar, node_id
    ) -> None:
        from nulloracle import NullAssignment, assignments_digest, decode_assignments, open_envelope

        composed_sidecar.write([NullAssignment(**assignment(node_id))])
        # The plaintext, recovered with the key, digests to the same value a
        # key-less process would compute from the declared assignments.
        plaintext = open_envelope(composed_sidecar.path.read_bytes(), composed_sidecar._key)
        assert set(decode_assignments(plaintext)) == {node_id}
        assert assignments_digest(decode_assignments(plaintext)) == assignments_digest(
            [NullAssignment(**assignment(node_id))]
        )


class TestTheSidecarJoinsTheTreeStore:
    def test_an_assignment_is_keyed_by_a_canonical_uuid(self, composed_sidecar) -> None:
        # §9.1's provenance discipline: the sidecar's key must join to the
        # tree store's node.id UUID PRIMARY KEY without a translation step,
        # or a node's assignment could not be looked up by the node's id.
        from nulloracle import NullAssignment, normalize_node_id

        raw = uuid.uuid4()
        composed_sidecar.write([NullAssignment(**assignment(str(raw).upper()))])
        stored = composed_sidecar.open()
        assert set(stored) == {str(raw)}
        assert composed_sidecar.assignment(raw) is not None
        assert normalize_node_id(raw) == str(raw)
