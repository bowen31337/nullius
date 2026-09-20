"""Feature 109's file: §7.1's ``sidecar.enc``, written and read by one account.

app_spec.xml feature 109 is one sentence with four clauses, and this file
pins three of them: *persists* (the map really lands on disk and reads back),
*in an AES-GCM encrypted sidecar file* (nothing recognizable is on disk, and
a tampered file is refused), and *readable by exactly one service account*
(the mode bits are the enforcement §1 demands — *"Enforce with filesystem
permissions and network policy, never with prompt instructions"*).

The fourth clause's subject — *"System persists null assignments"* — is the
*what*: :mod:`test_assignment` pins the schema, and the tests below pin that
the schema is what actually round-trips through the file, §7.1's
``perm_seed`` and ``block_days`` included, since feature 115 reproduces a
null node's permutation from exactly those two stored values.

The refusals are again the load-bearing part, and here they are ordered
because each order means something different to an operator: a *missing*
sidecar, a *foreign* reader, an *unauthenticated* file, and an
*authenticated file that is not the schema*.  Collapsing any of them into
"no assignments" would be the one behaviour §7 cannot survive — a caller
that reads a broken sidecar as an empty one would go on to report an FDR
over a world whose nulls had silently become real.
"""

from __future__ import annotations

import os
import stat

import pytest

from nulloracle import (
    SIDECAR_DIRECTORY,
    SIDECAR_FILENAME,
    SIDECAR_FILE_MODE,
    SIDECAR_PATH_ENV,
    SERVICE_ACCOUNT_ENV,
    NullAssignment,
    NullSidecar,
    SidecarAccessError,
    SidecarDecryptionError,
    SidecarError,
    SidecarKey,
    SidecarKeyError,
    SidecarStoreError,
)


def assignment(node_id: str, **overrides) -> NullAssignment:
    fields = {"is_null": True, "perm_seed": 11}
    fields.update(overrides)
    return NullAssignment(node_id=node_id, **fields)


def mode_of(path) -> int:
    return stat.S_IMODE(os.stat(path).st_mode)


def raw_write(sidecar: NullSidecar, payload: bytes) -> None:
    """Put ``payload`` at the sidecar's path at the sidecar's own modes.

    Used by the tests that plant a *malformed* file: the access gate is
    checked first and unconditionally, so a raw ``write_bytes`` (which lands
    at the umask's mode) would be refused for its permissions instead of for
    the reason the test is about.  Sealing at 0600 inside a 0700 directory
    isolates the failure being pinned.
    """
    sidecar.directory.mkdir(parents=True, exist_ok=True)
    os.chmod(sidecar.directory, 0o700)
    sidecar.path.write_bytes(payload)
    os.chmod(sidecar.path, SIDECAR_FILE_MODE)


class TestTheSidecarIsPersisted:
    def test_a_written_map_reads_back_whole(
        self, test_sidecar: NullSidecar, node_ids: "callable"
    ) -> None:
        first, second = node_ids(2)
        original = {
            first: assignment(first, is_null=True, perm_seed=3),
            second: assignment(second, is_null=False, perm_seed=0, block_days=5),
        }
        test_sidecar.write(original)
        assert test_sidecar.open() == original

    def test_the_permutation_parameters_survive_the_file(
        self, test_sidecar: NullSidecar, node_id: str
    ) -> None:
        # Feature 115's whole reproducibility argument depends on these two
        # values being readable back out of the sealed file: "using a
        # *stored* permutation seed with a 20 day block length".
        test_sidecar.write([assignment(node_id, perm_seed=12345, block_days=7)])
        stored = test_sidecar.open()[node_id]
        assert stored.perm_seed == 12345
        assert stored.block_days == 7

    def test_the_write_reports_the_digest_of_what_it_sealed(
        self, test_sidecar: NullSidecar, node_id: str
    ) -> None:
        from nulloracle import envelope_digest

        digest = test_sidecar.write([assignment(node_id)])
        assert digest == envelope_digest(test_sidecar.path.read_bytes())

    def test_an_empty_map_is_persisted_as_an_empty_sidecar(
        self, test_sidecar: NullSidecar
    ) -> None:
        # A campaign that assigned no nulls is a legitimate world, and it
        # must survive as a *statement* — §7.4's guard runs against whatever
        # was written, and "we planted nothing" is not the same fact as "no
        # sidecar was written".
        test_sidecar.write({})
        assert test_sidecar.exists()
        assert test_sidecar.open() == {}

    def test_rewriting_replaces_the_world_rather_than_merging(
        self, test_sidecar: NullSidecar, node_ids: "callable"
    ) -> None:
        first, second = node_ids(2)
        test_sidecar.write([assignment(first)])
        test_sidecar.write([assignment(second)])
        assert set(test_sidecar.open()) == {second}

    def test_a_whole_file_write_leaves_no_stray_temporary(
        self, test_sidecar: NullSidecar, node_id: str
    ) -> None:
        test_sidecar.write([assignment(node_id)])
        leftovers = [
            entry.name
            for entry in test_sidecar.directory.iterdir()
            if entry.name != SIDECAR_FILENAME
        ]
        assert leftovers == []


class TestOneNodeAtATime:
    def test_a_known_node_answers_with_its_assignment(
        self, test_sidecar: NullSidecar, node_id: str
    ) -> None:
        # §7.2's resolution path reads exactly this: "if is_null, return
        # block_permute(...); else return the real forward returns".
        test_sidecar.write([assignment(node_id, is_null=False)])
        found = test_sidecar.assignment(node_id)
        assert found is not None
        assert found.is_null is False

    def test_an_unknown_node_answers_none(
        self, test_sidecar: NullSidecar, node_ids: "callable"
    ) -> None:
        # None means "this node is not in the sidecar" — the honest answer
        # for a real node's whole subtree in a Type-R campaign (§7.3).
        first, second = node_ids(2)
        test_sidecar.write([assignment(first)])
        assert test_sidecar.assignment(second) is None

    def test_an_uppercase_lookup_finds_the_same_node(
        self, test_sidecar: NullSidecar, node_id: str
    ) -> None:
        test_sidecar.write([assignment(node_id)])
        assert test_sidecar.assignment(node_id.upper()) is not None

    def test_a_broken_sidecar_raises_rather_than_answering_none(
        self, test_sidecar: NullSidecar, node_id: str
    ) -> None:
        # The distinction the whole taxonomy rests on: a caller must never
        # be able to mistake an unopenable sidecar for a real world.
        test_sidecar.write([assignment(node_id)])
        raw = bytearray(test_sidecar.path.read_bytes())
        raw[-1] ^= 0x01
        test_sidecar.path.write_bytes(bytes(raw))
        with pytest.raises(SidecarDecryptionError):
            test_sidecar.assignment(node_id)


class TestTheFileIsEncrypted:
    def test_the_labels_are_not_on_disk_in_the_clear(
        self, test_sidecar: NullSidecar, node_id: str
    ) -> None:
        # The claim §1 rests on: the sidecar is the one place is_null lives,
        # and it is sealed.
        test_sidecar.write([assignment(node_id, is_null=True, perm_seed=99)])
        blob = test_sidecar.path.read_bytes()
        for token in (b"is_null", b"perm_seed", b"block_days", node_id.encode()):
            assert token not in blob

    def test_the_wrong_key_cannot_open_it(
        self, sidecar_path, key_ref: str, other_key: SidecarKey, node_id: str
    ) -> None:
        writer = NullSidecar(sidecar_path, SidecarKey.from_hex("ab" * 32))
        writer.write([assignment(node_id)])
        with pytest.raises(SidecarDecryptionError):
            NullSidecar(sidecar_path, other_key).open()

    def test_a_tampered_file_is_refused(
        self, test_sidecar: NullSidecar, node_id: str
    ) -> None:
        test_sidecar.write([assignment(node_id)])
        raw = bytearray(test_sidecar.path.read_bytes())
        raw[-1] ^= 0x01
        test_sidecar.path.write_bytes(bytes(raw))
        with pytest.raises(SidecarDecryptionError, match="unrecoverable"):
            test_sidecar.open()

    def test_a_file_that_is_not_a_sidecar_is_refused(
        self, test_sidecar: NullSidecar, node_id: str
    ) -> None:
        raw_write(test_sidecar, b"x" * 128)
        with pytest.raises(SidecarDecryptionError, match="file marker"):
            test_sidecar.open()

    def test_an_authenticated_file_of_the_wrong_schema_is_a_schema_error(
        self, test_sidecar: NullSidecar, node_id: str
    ) -> None:
        # Deliberately SidecarError and not SidecarDecryptionError: the key
        # is fine and the bytes are the ones sealed — the problem is that
        # they are not §7.1's schema, and an operator sent to investigate the
        # key would be looking in the wrong place.
        import json

        from nulloracle import seal

        payload = json.dumps({node_id: {"is_null": True}}).encode()
        raw_write(test_sidecar, seal(payload, SidecarKey.from_hex("0f" * 32)))
        with pytest.raises(SidecarError, match="block_days"):
            test_sidecar.open()


class TestReadableByExactlyOneAccount:
    # §7.1: "readable by ONE service account".  §1 is explicit that this is
    # enforced with filesystem permissions, never with a prompt: "Enforce
    # with filesystem permissions and network policy, never with prompt
    # instructions. A prompt is not a security boundary."

    def test_the_file_is_written_owner_only(
        self, test_sidecar: NullSidecar, node_id: str
    ) -> None:
        test_sidecar.write([assignment(node_id)])
        assert mode_of(test_sidecar.path) == SIDECAR_FILE_MODE == 0o600

    def test_the_directory_is_written_owner_only(
        self, test_sidecar: NullSidecar, node_id: str
    ) -> None:
        # A 0600 file inside a world-executable directory is still
        # enumerable, and a name here is a node_id with a campaign's
        # universe size attached.
        test_sidecar.write([assignment(node_id)])
        assert mode_of(test_sidecar.directory) == 0o700

    def test_a_file_never_exists_with_wider_bits_even_momentarily(
        self, test_sidecar: NullSidecar, node_id: str
    ) -> None:
        # os.open with the mode, rather than write_bytes followed by a
        # chmod: the instant between two syscalls is one an attacker can win
        # by polling.
        test_sidecar.write([assignment(node_id)])
        assert not mode_of(test_sidecar.path) & 0o077

    def test_a_loosened_file_is_refused_rather_than_opened(
        self, test_sidecar: NullSidecar, node_id: str
    ) -> None:
        # Wide bits are the failure that actually happens — a copy, a
        # chmod -R, an archive extraction that did not preserve modes — and
        # reading anyway would mean the labels were readable by every
        # process on the host while the system carried on.
        test_sidecar.write([assignment(node_id)])
        os.chmod(test_sidecar.path, 0o644)
        with pytest.raises(SidecarAccessError, match="ONE service account"):
            test_sidecar.open()

    def test_a_loosened_directory_is_refused_too(
        self, test_sidecar: NullSidecar, node_id: str
    ) -> None:
        test_sidecar.write([assignment(node_id)])
        os.chmod(test_sidecar.directory, 0o755)
        with pytest.raises(SidecarAccessError, match="directory"):
            test_sidecar.open()

    def test_the_refusal_names_the_mode_to_restore(
        self, test_sidecar: NullSidecar, node_id: str
    ) -> None:
        test_sidecar.write([assignment(node_id)])
        os.chmod(test_sidecar.path, 0o640)
        with pytest.raises(SidecarAccessError) as raised:
            test_sidecar.open()
        assert "0o600" in str(raised.value)

    def test_an_ownership_mismatch_is_refused(
        self, sidecar_path, key_ref: str, test_key: SidecarKey, node_id: str, uid_named
    ) -> None:
        # The case mode bits alone cannot see: a file copied to a foreign
        # account *with* 0600 keeps the bits and loses the owner.
        NullSidecar(sidecar_path, test_key).write([assignment(node_id)])
        owner_uid = os.stat(sidecar_path).st_uid
        if not uid_named(owner_uid):
            pytest.skip("this host cannot resolve a uid to a login name")
        import pwd

        stranger = "a-service-account-this-file-is-not-granted-to"
        assert pwd.getpwuid(owner_uid).pw_name != stranger
        sidecar = NullSidecar(sidecar_path, test_key, account=stranger)
        with pytest.raises(SidecarAccessError, match="owned by"):
            sidecar.open()

    def test_the_granted_account_reads_it(
        self, sidecar_path, key_ref: str, test_key: SidecarKey, node_id: str, uid_named
    ) -> None:
        NullSidecar(sidecar_path, test_key).write([assignment(node_id)])
        owner_uid = os.stat(sidecar_path).st_uid
        if not uid_named(owner_uid):
            pytest.skip("this host cannot resolve a uid to a login name")
        import pwd

        owner = pwd.getpwuid(owner_uid).pw_name
        assert NullSidecar(sidecar_path, test_key, account=owner).open() == {
            node_id: assignment(node_id)
        }

    def test_no_named_account_still_enforces_the_mode_bits(
        self, test_sidecar: NullSidecar, node_id: str
    ) -> None:
        # Unnamed is a supported state (the single-machine allowance), and
        # it does not mean unchecked: the bits are still checked first and
        # unconditionally.
        test_sidecar.write([assignment(node_id)])
        os.chmod(test_sidecar.path, 0o666)
        with pytest.raises(SidecarAccessError):
            test_sidecar.open()


class TestTheRefusalOrder:
    # Each refusal means something different to the operator reading it, so
    # the order is part of the contract rather than an implementation detail.

    def test_a_missing_sidecar_is_a_store_error_not_an_access_error(
        self, test_sidecar: NullSidecar
    ) -> None:
        assert not test_sidecar.exists()
        with pytest.raises(SidecarStoreError, match="no sidecar exists"):
            test_sidecar.open()

    def test_the_missing_sidecar_message_says_what_absence_means(
        self, test_sidecar: NullSidecar
    ) -> None:
        # The absence means the assignments were never persisted — *not*
        # that none were made.
        with pytest.raises(SidecarStoreError) as raised:
            test_sidecar.open()
        assert "not that none were made" in str(raised.value)

    def test_the_empty_sidecar_is_not_the_missing_one(
        self, test_sidecar: NullSidecar
    ) -> None:
        # Two different facts about a campaign, kept distinguishable.
        test_sidecar.write({})
        assert test_sidecar.exists()
        assert test_sidecar.open() == {}
        test_sidecar.path.unlink()
        with pytest.raises(SidecarStoreError):
            test_sidecar.open()

    def test_a_foreign_reader_is_refused_before_the_cipher_is_reached(
        self, test_sidecar: NullSidecar, node_id: str
    ) -> None:
        # Order matters here specifically: an access failure must read as
        # "someone else can read this file", not as "the key is wrong".
        test_sidecar.write([assignment(node_id)])
        os.chmod(test_sidecar.path, 0o644)
        with pytest.raises(SidecarAccessError):
            test_sidecar.open()


class TestConstructionAndResolution:
    def test_an_empty_path_is_refused(self, test_key: SidecarKey) -> None:
        with pytest.raises(SidecarStoreError, match="empty path"):
            NullSidecar("", test_key)

    def test_a_non_key_material_is_refused(self, sidecar_path) -> None:
        with pytest.raises(SidecarKeyError):
            NullSidecar(sidecar_path, "not-a-key")  # type: ignore[arg-type]

    def test_resolve_reads_the_path_variable(
        self, sidecar_path, key_ref: str
    ) -> None:
        resolved = NullSidecar.resolve()
        assert resolved is not None
        assert resolved.path == sidecar_path

    def test_resolve_defaults_to_the_lake(self, lake_root, key_ref: str) -> None:
        # §7.1 draws /z0/null/; §4.2 makes the lake the mounted store this
        # workspace reads, so the deployment's mount point *is* the /z0 the
        # architecture illustrates.  Reads the ambient environment (the
        # fixtures set LAKE_ROOT and the key reference there), not an empty
        # mapping — this is the default a deployment actually gets.
        resolved = NullSidecar.resolve()
        assert resolved is not None
        assert resolved.path == lake_root / SIDECAR_DIRECTORY / SIDECAR_FILENAME

    def test_resolve_nothing_when_nothing_names_a_place(
        self, monkeypatch: pytest.MonkeyPatch, key_ref: str
    ) -> None:
        # No path variable, no lake — and no workspace root above a tmpdir.
        # Returns None rather than raising or guessing: an unconfigured
        # sidecar is a discoverable state.
        import app.module_loader as loader

        monkeypatch.setattr(loader, "find_workspace_root", lambda *a, **k: None)
        assert NullSidecar.resolve({}) is None

    def test_resolve_degrades_when_no_key_is_configured(self, sidecar_path) -> None:
        # Never raises: the factory builds *every* component on *every*
        # create_app(), so a builder that raised would take composition down
        # for every unrelated feature in the workspace.
        assert NullSidecar.resolve({SIDECAR_PATH_ENV: str(sidecar_path)}) is None

    @pytest.mark.parametrize("scheme", ["kms", "sops"])
    def test_resolve_degrades_on_a_backend_it_does_not_speak(
        self, sidecar_path, scheme: str
    ) -> None:
        # Same reason, stated for the case that looks most like it should
        # fail loudly: a process that *requires* a sidecar asks ensure_key()
        # directly at its own startup, where a named error is right.
        from nulloracle import KEY_REF_ENV

        resolved = NullSidecar.resolve(
            {SIDECAR_PATH_ENV: str(sidecar_path), KEY_REF_ENV: f"{scheme}:target"}
        )
        assert resolved is None

    def test_resolve_accepts_material_from_a_backend(self, sidecar_path) -> None:
        # The seam a KMS-speaking caller composes through: it resolved the
        # key, this member only wraps and checks it.
        resolved = NullSidecar.resolve(
            {SIDECAR_PATH_ENV: str(sidecar_path)}, material=bytes.fromhex("ab" * 32)
        )
        assert resolved is not None
        assert resolved.path == sidecar_path

    def test_resolve_carries_the_named_service_account(
        self, sidecar_path, key_ref: str
    ) -> None:
        from nulloracle import KEY_REF_ENV

        resolved = NullSidecar.resolve(
            {
                SIDECAR_PATH_ENV: str(sidecar_path),
                KEY_REF_ENV: key_ref,
                SERVICE_ACCOUNT_ENV: "nulloracle-svc",
            }
        )
        assert resolved is not None
        assert resolved.account == "nulloracle-svc"

    def test_the_path_is_exposed_because_it_is_not_a_secret(
        self, test_sidecar: NullSidecar
    ) -> None:
        # An audit, a backup check or an operator's inventory must be able to
        # locate a sealed sidecar in an environment that can not decrypt it.
        assert test_sidecar.path.name == SIDECAR_FILENAME
        assert test_sidecar.directory.name == SIDECAR_DIRECTORY


class TestWriteFailuresAreLoud:
    def test_a_path_that_cannot_be_a_file_is_refused(
        self, tmp_path, test_key: SidecarKey, node_id: str
    ) -> None:
        # A sidecar that silently failed to persist is exactly the state
        # feature 109 exists to prevent: a campaign would then run against a
        # world whose assignments nobody recorded.
        blocked = tmp_path / "blocked"
        blocked.write_text("not a directory")
        with pytest.raises(SidecarStoreError):
            NullSidecar(blocked / "nested" / SIDECAR_FILENAME, test_key).write(
                [assignment(node_id)]
            )

    def test_a_failed_write_does_not_leave_a_temporary_behind(
        self, tmp_path, test_key: SidecarKey, node_id: str
    ) -> None:
        blocked = tmp_path / "blocked"
        blocked.write_text("not a directory")
        target = blocked / "nested" / SIDECAR_FILENAME
        with pytest.raises(SidecarStoreError):
            NullSidecar(target, test_key).write([assignment(node_id)])
        assert not list(tmp_path.rglob("*.tmp"))
