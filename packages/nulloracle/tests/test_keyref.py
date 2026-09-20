"""The sidecar key reference: where the key comes from, and who may ask.

app_spec.xml, "Null Oracle & Planted Nulls", depends_on 109 for feature 111:
*System resolves the sidecar decryption key from KMS or sops, which emits an
unrecoverable_state alert when decryption fails.*  This file pins the grammar
and the access rule that resolution runs behind — the half of feature 111
that can be tested honestly without a live KMS or an operator's sops key.
The backends themselves are deliberately not spoken here (see
:mod:`nulloracle.keyref`'s docstring for why a half-version of either would
be a second, disagreeing implementation of a credential path).

Two claims:

* **the reference grammar is closed.**  ``kms:``, ``sops:`` and ``hex:``,
  and everything else is refused by name.  A member that guessed would
  eventually load the wrong kind of secret — and the secret in question is
  the one §1 says voids every calibration number if it leaks.
* **exactly one account.**  §7.1 grants the sidecar to one service account
  and §18 repeats it (*"granted to exactly one service account"*).  A
  foreign caller is refused before it holds key material, so the rule holds
  at the API and not merely at the file.

The key wrapper's own claim — *that a key cannot leak by accident* — is
pinned at the bottom, because the ordinary ways a secret escapes are not
attacks: they are a traceback printing a local, or a failing assertion that
helpfully renders both sides.
"""

from __future__ import annotations

import pytest

from nulloracle import (
    KEY_REF_ENV,
    SIDECAR_KEY_BYTES,
    SERVICE_ACCOUNT_ENV,
    EnsureKeyResult,
    KeyReference,
    SidecarAccessError,
    SidecarKey,
    SidecarKeyError,
    ensure_key,
    resolve_key,
    service_account,
)

HEX_32 = "ab" * 32  # 64 hex characters == 32 bytes == AES-256


class TestTheReferenceGrammar:
    def test_a_kms_reference_parses(self) -> None:
        parsed = KeyReference.parse("kms:arn:aws:kms:eu-west-1:1234:key/abc")
        assert parsed.scheme == "kms"
        assert parsed.target == "arn:aws:kms:eu-west-1:1234:key/abc"

    def test_a_sops_reference_parses(self) -> None:
        parsed = KeyReference.parse("sops:/z0/null/key.enc.yaml")
        assert parsed.scheme == "sops"
        assert parsed.target == "/z0/null/key.enc.yaml"

    def test_a_hex_reference_parses(self) -> None:
        assert KeyReference.parse(f"hex:{HEX_32}").target == HEX_32

    def test_the_scheme_is_case_insensitive_and_trimmed(self) -> None:
        # A .env line or a YAML block scalar commonly carries whitespace; the
        # target is a path or an ARN and must not be edited, but the scheme
        # is this member's own vocabulary.
        assert KeyReference.parse("  KMS:  some-key  ").scheme == "kms"
        assert KeyReference.parse("  KMS:  some-key  ").target == "some-key"

    @pytest.mark.parametrize(
        "reference", ["", "   ", "some/path/with/no/scheme", "vault:secret/key", "env:FOO"]
    )
    def test_everything_else_is_refused_by_name(self, reference: str) -> None:
        with pytest.raises(SidecarKeyError):
            KeyReference.parse(reference)

    def test_a_bare_path_is_refused_because_it_is_ambiguous(self) -> None:
        # The same string is a sops document in one deployment and a raw key
        # file in another, and there is no way to tell them apart — so the
        # refusal names both accepted spellings rather than picking one.
        with pytest.raises(SidecarKeyError) as raised:
            KeyReference.parse("/z0/null/key.enc.yaml")
        assert "sops:<target>" in str(raised.value)
        assert "hex:<target>" in str(raised.value)

    def test_a_scheme_with_an_empty_target_is_refused(self) -> None:
        # Refused now, as the configuration mistake it is, rather than later
        # as a decryption error that sends an operator to the wrong file.
        with pytest.raises(SidecarKeyError, match="carries no target"):
            KeyReference.parse("kms:")

    def test_the_redacted_label_hides_the_target(self) -> None:
        # One accessor that is safe to log in every case: a KMS ARN and a
        # sops path are not secrets, but a hex: target is the key itself.
        parsed = KeyReference.parse(f"hex:{HEX_32}")
        assert HEX_32 not in parsed.scheme_label
        assert parsed.scheme_label == "hex:<redacted>"

    def test_a_non_string_reference_is_refused(self) -> None:
        with pytest.raises(SidecarKeyError, match="must be a string"):
            KeyReference.parse(None)  # type: ignore[arg-type]


class TestResolvingFromTheEnvironment:
    def test_the_reference_is_read_from_the_documented_variable(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(KEY_REF_ENV, f"hex:{HEX_32}")
        assert KeyReference.from_env().scheme == "hex"

    def test_an_unset_variable_is_refused_as_a_configuration_problem(self) -> None:
        # Raises rather than returning None: the *component* degrades to
        # absent when unconfigured, but a caller explicitly asking for the
        # reference has asked a question whose honest answer is "there is
        # none".
        with pytest.raises(SidecarKeyError, match=KEY_REF_ENV):
            KeyReference.from_env({})

    def test_a_blank_variable_counts_as_unset(self) -> None:
        with pytest.raises(SidecarKeyError):
            KeyReference.from_env({KEY_REF_ENV: "   "})

    def test_the_refusal_names_the_variable_a_deployment_must_set(self) -> None:
        with pytest.raises(SidecarKeyError) as raised:
            KeyReference.from_env({})
        assert "NULL_SIDECAR_KEY_REF" in str(raised.value)


class TestResolvingKeyMaterial:
    def test_an_inline_hex_reference_resolves(self) -> None:
        key = resolve_key(KeyReference.parse(f"hex:{HEX_32}"))
        assert len(key.reveal()) == SIDECAR_KEY_BYTES
        assert key.reveal() == bytes.fromhex(HEX_32)

    @pytest.mark.parametrize("scheme", ["kms", "sops"])
    def test_a_backend_this_member_does_not_speak_is_refused_by_name(
        self, scheme: str
    ) -> None:
        # Not a stub: the boundary.  Feature 111 owns the KMS call and the
        # sops decryption; this member owns the grammar they resolve behind,
        # and the refusal says which backend must supply the material.
        with pytest.raises(SidecarKeyError) as raised:
            resolve_key(KeyReference.parse(f"{scheme}:some-target"))
        assert repr(scheme) in str(raised.value)
        assert "ensure_key" in str(raised.value)

    def test_the_backend_refusal_hides_the_target(self) -> None:
        # A message about a failed key resolution is a message that ends up
        # in a log, so it must not carry the target — for hex: that target
        # is the key.
        with pytest.raises(SidecarKeyError) as raised:
            resolve_key(KeyReference.parse(f"hex:{'cd' * 31}zz"))
        assert "cd" * 31 not in str(raised.value)


class TestExactlyOneServiceAccount:
    # §7.1: "readable by ONE service account".  Enforced at the file by mode
    # bits (see test_sidecar.py); stated again here, at the API, so a caller
    # cannot reach a key by importing past the file.

    def test_the_granted_account_resolves(self) -> None:
        key = resolve_key(
            KeyReference.parse(f"hex:{HEX_32}"),
            account="nulloracle-svc",
            granted_account="nulloracle-svc",
        )
        assert isinstance(key, SidecarKey)

    def test_a_foreign_account_is_refused_before_it_holds_anything(self) -> None:
        with pytest.raises(SidecarAccessError) as raised:
            resolve_key(
                KeyReference.parse(f"hex:{HEX_32}"),
                account="scoring-svc",
                granted_account="nulloracle-svc",
            )
        assert "scoring-svc" in str(raised.value)
        assert "ONE service account" in str(raised.value)

    def test_the_account_variable_names_one_account(self) -> None:
        assert service_account({SERVICE_ACCOUNT_ENV: " nulloracle-svc "}) == (
            "nulloracle-svc"
        )

    def test_an_unnamed_account_is_a_supported_state(self) -> None:
        # None means "this deployment has not named an account", in which
        # case the mode bits are the whole enforcement.  Requiring a name
        # would refuse to compose in the single-machine configuration the
        # spec explicitly allows — and naming one *adds* a check rather than
        # gating one.
        assert service_account({}) is None
        assert service_account({SERVICE_ACCOUNT_ENV: "  "}) is None

    def test_no_named_account_means_no_identity_check(self) -> None:
        assert isinstance(
            resolve_key(KeyReference.parse(f"hex:{HEX_32}"), account="anyone"), SidecarKey
        )


class TestEnsureKey:
    def test_supplied_material_is_the_key(self) -> None:
        result = ensure_key(bytes.fromhex(HEX_32))
        assert isinstance(result, EnsureKeyResult)
        assert result.key.reveal() == bytes.fromhex(HEX_32)

    def test_supplied_material_is_not_reported_as_created(self) -> None:
        # The backend knows whether it minted a key; this member has no way
        # to ask, so it never claims to have created one.  Feature 155's
        # backup obligation hangs on this flag.
        assert ensure_key(bytes.fromhex(HEX_32)).created is False

    def test_an_inline_reference_resolves_through_ensure_key(self) -> None:
        result = ensure_key(env={KEY_REF_ENV: f"hex:{HEX_32}"})
        assert result.key.reveal() == bytes.fromhex(HEX_32)

    def test_a_backend_reference_is_refused_with_the_seam_named(self) -> None:
        with pytest.raises(SidecarKeyError, match="ensure_key"):
            ensure_key(env={KEY_REF_ENV: "kms:arn:aws:kms:eu-west-1:1:key/x"})

    def test_a_foreign_account_is_refused_on_the_supplied_path_too(self) -> None:
        # The rule is enforced on *both* paths that reach material: one path
        # checked and the other not is the class of bug §7.1 cannot afford.
        with pytest.raises(SidecarAccessError):
            ensure_key(
                bytes.fromhex(HEX_32),
                env={SERVICE_ACCOUNT_ENV: "nulloracle-svc"},
                account="scoring-svc",
            )

    def test_the_account_defaults_to_the_configured_one(self) -> None:
        result = ensure_key(
            bytes.fromhex(HEX_32), env={SERVICE_ACCOUNT_ENV: "nulloracle-svc"}
        )
        assert result.key.reveal() == bytes.fromhex(HEX_32)


class TestTheKeyDoesNotLeakByAccident:
    def test_repr_redacts_the_material(self) -> None:
        key = SidecarKey(bytes.fromhex(HEX_32))
        assert HEX_32 not in repr(key)
        assert "redacted" in repr(key)

    def test_str_redacts_the_material(self) -> None:
        # str falls back to repr by default, which is exactly the accident
        # this pins: an f-string in a log line must not print the key.
        key = SidecarKey(bytes.fromhex(HEX_32))
        assert HEX_32 not in str(key)
        assert HEX_32 not in f"{key}"

    def test_a_key_does_not_compare_equal_to_its_own_bytes(self) -> None:
        # A comparison against the raw secret is a leak dressed as an
        # assertion; it reads as "not equal" rather than as supported.
        key = SidecarKey(bytes.fromhex(HEX_32))
        assert key != bytes.fromhex(HEX_32)
        assert key != HEX_32
        assert key == SidecarKey(bytes.fromhex(HEX_32))

    def test_a_debugger_dump_of_an_object_holding_a_key_redacts_it(self) -> None:
        # The realistic leak: a dataclass or a local rendered by a failing
        # assertion.  repr is what such a rendering uses, and it redacts.
        holder = {"key": SidecarKey(bytes.fromhex(HEX_32))}
        assert HEX_32 not in repr(holder)

    def test_the_material_is_only_reachable_through_reveal(self) -> None:
        key = SidecarKey(bytes.fromhex(HEX_32))
        assert key.reveal() == bytes.fromhex(HEX_32)
        assert not hasattr(key, "value")
        assert not hasattr(key, "_SidecarKey__material")

    def test_a_malformed_hex_key_names_the_reason(self) -> None:
        # "invalid key" alone sends an operator to the sidecar when the
        # problem is the secret they pasted.
        with pytest.raises(SidecarKeyError, match="0-9a-f"):
            SidecarKey.from_hex("zz" * 32)

    def test_an_odd_length_hex_key_names_the_reason(self) -> None:
        with pytest.raises(SidecarKeyError, match="odd"):
            SidecarKey.from_hex("a" * 63)

    def test_a_wrong_length_hex_key_names_the_length(self) -> None:
        with pytest.raises(SidecarKeyError, match="exactly 32"):
            SidecarKey.from_hex("ab" * 16)

    def test_a_non_bytes_material_is_refused(self) -> None:
        with pytest.raises(SidecarKeyError, match="must be bytes"):
            SidecarKey("not-bytes")  # type: ignore[arg-type]
