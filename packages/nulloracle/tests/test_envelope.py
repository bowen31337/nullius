"""The AES-GCM container: the sidecar file's bytes.

app_spec.xml feature 109 says the sidecar is *AES-GCM* encrypted.  §7.1
names the primitive and the storage location in one line and nothing more,
so the container's layout is pinned by this member — see
:mod:`nulloracle.envelope`'s docstring — and this file pins that pinning.

Three claims, each able to fail on its own:

* **it really is authenticated encryption.**  A single flipped bit anywhere
  in the file is refused.  This is the claim §1 rests on: the labels are
  sealed so that *"a leak here silently voids every calibration number the
  system has ever produced, and you would not notice"* — an unauthenticated
  mode would make a tampered sidecar an undetectable wrong world.
* **the nonce is never reused.**  Two seals of the *same* plaintext under
  the *same* key are two different files.  GCM's catastrophic failure is
  nonce reuse under one key (it leaks plaintext XOR and the authentication
  key), so "the nonce is fresh per seal" is not hygiene here, it is the
  construction's safety condition, and it is asserted directly.
* **the container's claims are checked before the key is used.**  A file
  that is not a sidecar, and a sidecar of a version this build does not
  write, are refused at the header — so an operator reading the traceback
  can tell "this is not a sidecar" from "this is a sidecar and the key is
  wrong", without the error ever becoming a decryption oracle.
"""

from __future__ import annotations

import pytest

from nulloracle import (
    FORMAT_VERSION,
    MAGIC,
    NONCE_BYTES,
    SidecarDecryptionError,
    SidecarKey,
    SidecarKeyError,
    envelope_digest,
    open_envelope,
    seal,
)

PLAINTEXT = b'{"a-node": {"is_null": true}}'

# The byte offsets the container's layout fixes, spelled once so the tests
# below read as "this field" rather than as arithmetic.
_HEADER = len(MAGIC) + 1 + NONCE_BYTES


class TestTheRoundTrip:
    def test_sealing_and_opening_returns_the_exact_plaintext(
        self, test_key: SidecarKey
    ) -> None:
        assert open_envelope(seal(PLAINTEXT, test_key), test_key) == PLAINTEXT

    def test_an_empty_plaintext_round_trips(self, test_key: SidecarKey) -> None:
        # A campaign that assigned no nulls seals b"{}"; the envelope itself
        # has no opinion about emptiness.
        assert open_envelope(seal(b"", test_key), test_key) == b""

    def test_the_file_is_not_the_plaintext(self, test_key: SidecarKey) -> None:
        sealed = seal(PLAINTEXT, test_key)
        assert PLAINTEXT not in sealed
        assert sealed.startswith(MAGIC)

    def test_the_layout_is_the_one_the_module_documents(
        self, test_key: SidecarKey
    ) -> None:
        sealed = seal(PLAINTEXT, test_key)
        assert sealed[: len(MAGIC)] == MAGIC
        assert sealed[len(MAGIC)] == FORMAT_VERSION
        # magic + version + nonce + ciphertext(len(plaintext)) + tag(16)
        assert len(sealed) == _HEADER + len(PLAINTEXT) + 16

    def test_a_raw_byte_key_is_accepted_and_equivalent(
        self, test_key: SidecarKey
    ) -> None:
        # A caller holding material from a backend can seal without building
        # the wrapper; the wrapping (and the length check) still happens.
        assert (
            open_envelope(seal(PLAINTEXT, test_key.reveal()), test_key)
            == PLAINTEXT
        )


class TestTheNonceIsFreshPerSeal:
    def test_the_same_plaintext_seals_to_two_different_files(
        self, test_key: SidecarKey
    ) -> None:
        # The safety condition of GCM: the same key must never see the same
        # nonce twice.  If the nonce were derived rather than drawn, these
        # two files would be identical — and an attacker holding both would
        # have the XOR of two plaintexts and the authentication key.
        first = seal(PLAINTEXT, test_key)
        second = seal(PLAINTEXT, test_key)
        assert first != second

    def test_the_nonces_differ_and_not_merely_the_ciphertext(
        self, test_key: SidecarKey
    ) -> None:
        first = seal(PLAINTEXT, test_key)
        second = seal(PLAINTEXT, test_key)
        first_nonce = first[len(MAGIC) + 1 : _HEADER]
        second_nonce = second[len(MAGIC) + 1 : _HEADER]
        assert len(first_nonce) == NONCE_BYTES
        assert first_nonce != second_nonce

    def test_both_files_still_open_to_the_same_plaintext(
        self, test_key: SidecarKey
    ) -> None:
        # ...because a fresh nonce is not a new world, it is the same world
        # written twice — which is what makes an idempotent re-write safe.
        first = seal(PLAINTEXT, test_key)
        second = seal(PLAINTEXT, test_key)
        assert open_envelope(first, test_key) == open_envelope(second, test_key)


class TestAuthentication:
    # Every byte of the file is covered: the header as associated data, the
    # body by the ciphertext itself.

    @pytest.mark.parametrize("position", [0, 5, 15, 16, _HEADER, _HEADER + 3, -1, -17])
    def test_a_single_flipped_bit_anywhere_is_refused(
        self, test_key: SidecarKey, position: int
    ) -> None:
        sealed = bytearray(seal(PLAINTEXT, test_key))
        sealed[position] ^= 0x01
        with pytest.raises(SidecarDecryptionError):
            open_envelope(bytes(sealed), test_key)

    def test_a_truncated_file_is_refused(self, test_key: SidecarKey) -> None:
        sealed = seal(PLAINTEXT, test_key)
        with pytest.raises(SidecarDecryptionError, match="truncated"):
            open_envelope(sealed[: _HEADER + 4], test_key)

    def test_a_file_shorter_than_the_container_is_refused(
        self, test_key: SidecarKey
    ) -> None:
        with pytest.raises(SidecarDecryptionError, match="shorter than"):
            open_envelope(b"", test_key)

    def test_the_wrong_key_is_refused(self, test_key: SidecarKey, other_key: SidecarKey) -> None:
        with pytest.raises(SidecarDecryptionError, match="authentication"):
            open_envelope(seal(PLAINTEXT, test_key), other_key)

    def test_a_forged_header_is_refused(self, test_key: SidecarKey) -> None:
        # The header is passed to GCM as associated data, so a version byte
        # an attacker rewrites is not a downgrade — it is a tag failure.
        # Without AAD, a reader supporting two formats could be steered onto
        # the wrong one.
        sealed = bytearray(seal(PLAINTEXT, test_key))
        sealed[len(MAGIC)] = FORMAT_VERSION + 1
        with pytest.raises(SidecarDecryptionError):
            open_envelope(bytes(sealed), test_key)

    def test_the_refusal_does_not_say_which_way_it_failed(
        self, test_key: SidecarKey, other_key: SidecarKey
    ) -> None:
        # A wrong key and a tampered file must not be distinguishable to a
        # caller guessing keys — that is the whole content of "not an oracle".
        with pytest.raises(SidecarDecryptionError) as wrong_key:
            open_envelope(seal(PLAINTEXT, test_key), other_key)
        tampered = bytearray(seal(PLAINTEXT, test_key))
        tampered[-1] ^= 0xFF
        with pytest.raises(SidecarDecryptionError) as altered:
            open_envelope(bytes(tampered), test_key)
        assert str(wrong_key.value) == str(altered.value)

    def test_a_refusal_names_the_unrecoverable_failure(self, test_key: SidecarKey) -> None:
        with pytest.raises(SidecarDecryptionError) as raised:
            open_envelope(seal(b"x", test_key), SidecarKey.from_hex("2d" * 32))
        assert "unrecoverable" in str(raised.value)


class TestTheHeaderIsCheckedBeforeTheKey:
    def test_a_file_that_is_not_a_sidecar_is_refused_by_its_marker(
        self, test_key: SidecarKey
    ) -> None:
        with pytest.raises(SidecarDecryptionError, match="file marker"):
            open_envelope(b"not a sidecar at all, but long enough to try!!", test_key)

    def test_a_newer_container_version_is_refused_by_name(
        self, test_key: SidecarKey
    ) -> None:
        sealed = bytearray(seal(PLAINTEXT, test_key))
        sealed[len(MAGIC)] = FORMAT_VERSION + 7
        with pytest.raises(SidecarDecryptionError, match="container format 8"):
            open_envelope(bytes(sealed), test_key)

    def test_the_marker_mismatch_is_not_a_key_complaint(
        self, test_key: SidecarKey
    ) -> None:
        # The distinction an operator needs: "wrong file" is not "wrong key".
        with pytest.raises(SidecarDecryptionError) as raised:
            open_envelope(b"x" * 64, test_key)
        assert "not a sealed null sidecar" in str(raised.value)
        assert "authentication" not in str(raised.value)


class TestKeyValidation:
    def test_a_short_key_is_refused_as_a_key_length_mistake(self) -> None:
        # AES-128 is not accepted (see nulloracle.keyref): one length, named,
        # so there is never a question at a read about which one a file used.
        with pytest.raises(SidecarKeyError, match="exactly 32"):
            seal(PLAINTEXT, b"short")

    def test_a_raw_key_of_the_wrong_length_is_refused(self, test_key: SidecarKey) -> None:
        with pytest.raises(SidecarKeyError, match="exactly 32"):
            open_envelope(seal(PLAINTEXT, test_key), b"\x00" * 16)

    def test_a_key_of_neither_shape_is_refused(self, test_key: SidecarKey) -> None:
        with pytest.raises(SidecarKeyError, match="SidecarKey or 32 raw bytes"):
            seal(PLAINTEXT, "a-string-key")

    def test_a_non_bytes_plaintext_is_refused(self, test_key: SidecarKey) -> None:
        with pytest.raises(SidecarKeyError, match="must be bytes"):
            seal('{"a": 1}', test_key)  # type: ignore[arg-type]


class TestTheEnvelopeDigest:
    # What a process that may not hold the key can still compute: "is this
    # the same file?"  It detects a *different* sidecar and cannot detect a
    # *forged* one — only the tag does that — and the tests below keep those
    # two claims apart.

    def test_it_is_sixty_four_lowercase_hex(self, test_key: SidecarKey) -> None:
        digest = envelope_digest(seal(PLAINTEXT, test_key))
        assert len(digest) == 64 and digest == digest.lower()

    def test_two_seals_of_one_plaintext_have_different_digests(
        self, test_key: SidecarKey
    ) -> None:
        # ...because the nonces differ, so the files differ.  The digest is
        # over the file, not over the world; that is exactly why it is not a
        # substitute for the tag.
        assert envelope_digest(seal(PLAINTEXT, test_key)) != envelope_digest(
            seal(PLAINTEXT, test_key)
        )

    def test_one_file_has_one_digest(self, test_key: SidecarKey) -> None:
        sealed = seal(PLAINTEXT, test_key)
        assert envelope_digest(sealed) == envelope_digest(sealed)

    def test_it_answers_about_a_malformed_file_rather_than_refusing(
        self, test_key: SidecarKey
    ) -> None:
        # Its subject is the file, and a digest that refused a malformed
        # input could not answer the one question it is asked about a file
        # already suspected to be wrong.
        assert len(envelope_digest(b"garbage")) == 64

    def test_a_non_bytes_subject_is_refused(self) -> None:
        with pytest.raises(SidecarDecryptionError, match="must be bytes"):
            envelope_digest("garbage")  # type: ignore[arg-type]
