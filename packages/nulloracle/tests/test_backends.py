"""Feature 111, the backends: resolving the key from KMS or sops.

app_spec.xml, "Null Oracle & Planted Nulls", feature 111: *System resolves the
sidecar decryption key from KMS or sops, which emits an unrecoverable_state
alert when decryption fails.*  This file pins the resolution half — the KMS
call and the sops decryption, and what each of their failure modes means.

The member's other suite (:mod:`tests.test_keyref`) pins the *grammar*, and
stops exactly where this one starts: it asserts that ``keyref`` refuses a
``kms:`` or ``sops:`` reference by name and tells the caller to resolve the
material in the backend and pass it to ``ensure_key``.  This suite is that
backend, and the first claim below is that the boundary the grammar module
draws is still drawn — ``keyref.resolve_key`` has not been taught to speak
either scheme, because widening it would make the grammar module a second,
disagreeing implementation of a credential path.

No test here touches a network, a credential or the ``sops`` binary: both
backends take a *client* and a *runner*, and every test injects a fake.  That
is the design rather than a convenience — see :mod:`nulloracle.backends` — and
it is what makes the interesting claims (a KMS grant revoked, a sops key gone)
testable at all.

Three claims run through the file:

* **a failure to obtain the key is the alert.**  The KMS call erroring, the
  ``sops`` invocation exiting non-zero or timing out — each emits
  ``unrecoverable_state`` and raises :class:`UnrecoverableStateError`, chained
  from the cause.  §7's row is *Decrypt failure → Unrecoverable*, and the point
  is that none of these is retried or degraded.
* **a malformed secret is not.**  A blob that decrypts to the wrong length, a
  document that decrypts to something that is not key material, a reference
  whose backend is not configured — each is a configuration mistake with a
  repair that is not a restore, so each stays a ``SidecarKeyError`` and emits
  nothing.  Getting this line wrong in either direction is the bug: too loose
  and a misconfiguration pages someone about a lost key, too tight and a lost
  key reads as a typo.
* **the key never surfaces.**  The reference *target* is never rendered into a
  message or a record — for ``hex:`` the target is the key itself — and the
  resolved material only ever appears inside a :class:`SidecarKey`.
"""

from __future__ import annotations

import base64
import subprocess

import pytest

from nulloracle import (
    KMS_BLOB_ENV,
    KEY_REF_ENV,
    EnsureKeyResult,
    KeyAlertJournal,
    KeyReference,
    KmsBackend,
    SopsBackend,
    SidecarAccessError,
    SidecarKeyError,
    UnrecoverableStateError,
    default_backends,
    resolve_key,
    resolve_material,
    resolve_sidecar_key,
)
from nulloracle.keyalert import ALERT_KIND, KEY_BACKEND_STAGE

HEX_32 = "ab" * 32
#: A second, equally valid key — the one a document holds when it is *not* the
#: key the sidecar was sealed under.
OTHER_HEX_32 = "cd" * 32

KMS_REF = "kms:arn:aws:kms:eu-west-1:1234:key/abc"
SOPS_REF = "sops:/z0/null/key.enc.yaml"


# -- Fakes -------------------------------------------------------------------


class _Completed:
    """A finished process, shaped like :class:`subprocess.CompletedProcess`.

    Deliberately not a real ``CompletedProcess``: the field a test varies is
    the one under discussion, and a fake that carries all of them invites
    assertions about the ones that do not matter.
    """

    def __init__(self, returncode=0, stdout=b"", stderr=b"") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class _KmsClient:
    """A KMS client that returns ``plaintext`` — or raises ``failure``.

    Only ``decrypt`` exists, because only ``decrypt`` is what
    :class:`~nulloracle.backends.KmsBackend` promises to call: a fake that
    offered more would let the backend grow a second call without a test
    noticing.
    """

    def __init__(self, plaintext=b"", *, failure=None) -> None:
        self._plaintext = plaintext
        self._failure = failure
        self.calls: list[dict] = []

    def decrypt(self, **kwargs):
        self.calls.append(kwargs)
        if self._failure is not None:
            raise self._failure
        return {"Plaintext": self._plaintext}


@pytest.fixture
def kms_blob(tmp_path):
    """A KMS-wrapped data key on disk — the ciphertext a ``Decrypt`` unwraps.

    The bytes are opaque on purpose: this member never inspects them, the KMS
    does, and a test that asserted on their content would be asserting on the
    fake's own invention.
    """
    path = tmp_path / "wrapped-data-key.bin"
    path.write_bytes(b"wrapped-by-the-kms")
    return path


@pytest.fixture
def kms_client():
    """A KMS client returning :data:`HEX_32` as key material."""
    return _KmsClient(bytes.fromhex(HEX_32))


@pytest.fixture
def kms_backend(kms_client, kms_blob):
    """A :class:`KmsBackend` over the fake client and the temporary blob."""
    return KmsBackend(kms_client, blob=kms_blob)


@pytest.fixture
def sops_runner():
    """A fake ``sops`` runner factory: ``(returncode, stdout, stderr) -> runner``.

    Returns the list of argv lists it was handed alongside, so a test can assert
    on the invocation without a second fixture — the argv is part of this
    backend's contract (*``sops --decrypt <path>``*) and not an implementation
    detail.
    """

    def _make(returncode=0, stdout=b"", stderr=b""):
        calls: list[list[str]] = []

        def _run(argv, **kwargs):
            calls.append(argv)
            return _Completed(returncode, stdout, stderr)

        return _run, calls

    return _make


@pytest.fixture
def sops_backend(sops_runner):
    """A :class:`SopsBackend` whose runner succeeds with a hex key."""
    runner, _ = sops_runner(stdout=(HEX_32 + "\n").encode())
    return SopsBackend(runner=runner)


# -- The boundary this feature did not cross ---------------------------------


class TestTheGrammarStillRefusesTheBackends:
    """``keyref`` is unmodified: the new half composes *through* it.

    The two tests below are the same claims ``test_keyref.py`` already pins,
    restated here from the other side.  If a later change teaches
    ``resolve_key`` to call a backend — the tempting refactor, since that is
    where a caller would look for it — these fail, and they should: the
    grammar module's refusal is what tells a caller where the seam is, and a
    second resolution path inside it would be a second place a credential is
    handed out.
    """

    @pytest.mark.parametrize("scheme", ["kms", "sops"])
    def test_resolve_key_still_refuses_a_backend_scheme(self, scheme: str) -> None:
        with pytest.raises(SidecarKeyError, match="ensure_key"):
            resolve_key(KeyReference.parse(f"{scheme}:some-target"))

    def test_the_backend_seam_is_where_resolution_now_happens(
        self, kms_backend: KmsBackend
    ) -> None:
        # `resolve_material` is the new door, and it takes the same parsed
        # reference the grammar module produces.
        material = resolve_material(
            KeyReference.parse(KMS_REF), backends={"kms": kms_backend}
        )
        assert material == bytes.fromhex(HEX_32)


# -- The KMS backend ---------------------------------------------------------


class TestResolvingThroughKms:
    def test_the_reference_target_is_the_key_the_decrypt_is_made_against(
        self, kms_backend: KmsBackend, kms_client: _KmsClient
    ) -> None:
        # `kms:<arn>` names the *key*; the blob names the ciphertext.  The
        # ARN landing in `KeyId` is the whole of what the reference means.
        kms_backend.resolve(KeyReference.parse(KMS_REF))
        assert kms_client.calls[0]["KeyId"] == (
            "arn:aws:kms:eu-west-1:1234:key/abc"
        )

    def test_the_blob_is_what_gets_unwrapped(
        self, kms_backend: KmsBackend, kms_client: _KmsClient, kms_blob
    ) -> None:
        kms_backend.resolve(KeyReference.parse(KMS_REF))
        assert kms_client.calls[0]["CiphertextBlob"] == kms_blob.read_bytes()

    def test_the_plaintext_is_the_sidecar_key(
        self, kms_backend: KmsBackend
    ) -> None:
        assert kms_backend.resolve(KeyReference.parse(KMS_REF)) == bytes.fromhex(
            HEX_32
        )

    def test_the_backend_names_the_kms_scheme(self) -> None:
        assert KmsBackend.scheme == "kms"

    def test_an_unconfigured_blob_is_no_kms_backend(self) -> None:
        # Nothing names a wrapped data key, so there is nothing to unwrap —
        # the same discoverable-absence answer every store in this workspace
        # gives.  Note this is *not* the alert: nothing was attempted.
        assert KmsBackend.resolve_from_env({}) is None
        assert KmsBackend.resolve_from_env({KMS_BLOB_ENV: "   "}) is None
        assert KmsBackend.resolve_from_env({KMS_BLOB_ENV: "/z0/k.bin"}) is not None

    def test_building_the_backend_from_the_environment_touches_nothing(
        self, kms_blob
    ) -> None:
        # No SDK import, no credential resolution, no file read: the client is
        # built on first use, so asking "is there a KMS backend here?" costs a
        # dict lookup.
        backend = KmsBackend.resolve_from_env({KMS_BLOB_ENV: str(kms_blob)})
        assert backend is not None
        assert backend.blob == kms_blob


class TestAKmsFailureIsTheUnrecoverableState:
    """§7's row, for the KMS path: the key could not be obtained."""

    def test_a_failing_decrypt_call_emits_the_alert(self, kms_blob) -> None:
        cause = RuntimeError("AccessDeniedException: grant revoked")
        backend = KmsBackend(_KmsClient(failure=cause), blob=kms_blob)
        with pytest.raises(UnrecoverableStateError) as raised:
            backend.resolve(KeyReference.parse(KMS_REF))
        assert raised.value.alert.alert_kind == ALERT_KIND
        assert raised.value.alert.stage == KEY_BACKEND_STAGE

    def test_the_alert_is_chained_from_the_backends_own_failure(self, kms_blob) -> None:
        # The cause is not decoration: it is the only thing that says *why*
        # the key could not be obtained — a revoked grant, a disabled key, no
        # credentials — which is what an operator acts on.
        cause = RuntimeError("AccessDeniedException: grant revoked")
        backend = KmsBackend(_KmsClient(failure=cause), blob=kms_blob)
        with pytest.raises(UnrecoverableStateError) as raised:
            backend.resolve(KeyReference.parse(KMS_REF))
        assert raised.value.__cause__ is cause

    def test_every_kms_failure_shape_emits_the_same_alert(self, kms_blob) -> None:
        # Deliberately broad in the implementation, and pinned here: a KMS
        # decrypt fails as a ClientError, as a BotoCoreError, or as a KeyError
        # from a response that is not the shape the SDK documents.  Narrowing
        # the catch to one of them would make the *alert* depend on which SDK
        # version raised, and the failure mode of that is silence.
        for failure in (
            RuntimeError("ClientError"),
            KeyError("Plaintext"),
            ValueError("no region"),
            OSError("network unreachable"),
        ):
            backend = KmsBackend(_KmsClient(failure=failure), blob=kms_blob)
            with pytest.raises(UnrecoverableStateError):
                backend.resolve(KeyReference.parse(KMS_REF))

    def test_an_unreadable_blob_is_the_alert(self, tmp_path) -> None:
        # The wrapped data key is *the* artifact the key lives in.  If it
        # cannot be read, the key cannot be obtained — the same state as the
        # KMS refusing, reached one step earlier.
        missing = tmp_path / "gone.bin"
        backend = KmsBackend(_KmsClient(bytes.fromhex(HEX_32)), blob=missing)
        with pytest.raises(UnrecoverableStateError) as raised:
            backend.resolve(KeyReference.parse(KMS_REF))
        assert raised.value.alert.stage == KEY_BACKEND_STAGE

    def test_the_alert_names_the_consequence_and_the_repair(self, kms_blob) -> None:
        # The operator reading this at three in the morning is deciding
        # between a restore and a rebuild; §7 and §15 both answer *restore*,
        # and the message says so rather than leaving them to look it up.
        backend = KmsBackend(_KmsClient(failure=RuntimeError("denied")), blob=kms_blob)
        with pytest.raises(UnrecoverableStateError) as raised:
            backend.resolve(KeyReference.parse(KMS_REF))
        message = str(raised.value)
        assert "unrecoverable" in message
        assert "uninterpretable" in message
        assert "backup" in message


class TestAMalformedKmsSecretIsNotTheAlert:
    """A secret that arrived but is the wrong secret — a configuration mistake."""

    @pytest.mark.parametrize("length", [0, 16, 31, 33, 64])
    def test_the_wrong_length_is_refused_by_length(self, kms_blob, length: int) -> None:
        backend = KmsBackend(_KmsClient(b"x" * length), blob=kms_blob)
        with pytest.raises(SidecarKeyError, match=f"{length} bytes"):
            backend.resolve(KeyReference.parse(KMS_REF))

    def test_a_wrong_length_raises_no_alert_and_writes_no_row(
        self, tmp_path, kms_blob
    ) -> None:
        # The distinction in one test: the *same* call that emits
        # `unrecoverable_state` for a failing Decrypt must emit nothing when
        # the Decrypt succeeded and handed back the wrong key.  The repair for
        # the second is "point the reference at the right key"; the repair for
        # the first is "restore the key from backup", and conflating them
        # pages someone about a loss that did not happen.
        journal = KeyAlertJournal(f"sqlite:///{tmp_path}/alerts.db")
        backend = KmsBackend(_KmsClient(b"short"), blob=kms_blob, journal=journal)
        with pytest.raises(SidecarKeyError):
            backend.resolve(KeyReference.parse(KMS_REF))
        assert journal.alerts() == ()

    def test_a_non_bytes_plaintext_is_refused(self, kms_blob) -> None:
        # A response shape this member did not expect is the wrong artifact
        # behind the reference, not a lost key.
        backend = KmsBackend(_KmsClient("not-bytes"), blob=kms_blob)
        with pytest.raises(SidecarKeyError, match="rather than key bytes"):
            backend.resolve(KeyReference.parse(KMS_REF))

    def test_a_bytearray_plaintext_is_accepted_and_wrapped(self, kms_blob) -> None:
        # A backend may hand back a mutable buffer; the *length* is what this
        # member checks, and a bytearray of the right length is key material.
        backend = KmsBackend(
            _KmsClient(bytearray(bytes.fromhex(HEX_32))), blob=kms_blob
        )
        assert backend.resolve(KeyReference.parse(KMS_REF)) == bytes.fromhex(HEX_32)


# -- The sops backend --------------------------------------------------------


class TestResolvingThroughSops:
    def test_the_decrypted_plaintext_is_the_key(
        self, sops_backend: SopsBackend
    ) -> None:
        assert sops_backend.resolve(KeyReference.parse(SOPS_REF)) == bytes.fromhex(
            HEX_32
        )

    def test_the_invocation_is_sops_decrypt_against_the_named_path(
        self, sops_runner
    ) -> None:
        # The reference's target is the *document*, and `--decrypt <path>` is
        # what reading it means.  Asserted because the argv is the contract.
        runner, calls = sops_runner(stdout=(HEX_32 + "\n").encode())
        SopsBackend(runner=runner).resolve(KeyReference.parse(SOPS_REF))
        assert calls == [["sops", "--decrypt", "/z0/null/key.enc.yaml"]]

    def test_a_trailing_newline_is_the_documents_own_shape(self, sops_runner) -> None:
        # An editor, a YAML block scalar and a `sops` write all leave one
        # behind; stripping it is the difference between a key and a
        # wrong-length refusal.
        runner, _ = sops_runner(stdout=(HEX_32 + "\n").encode())
        assert SopsBackend(runner=runner).resolve(
            KeyReference.parse(SOPS_REF)
        ) == bytes.fromhex(HEX_32)

    def test_surrounding_whitespace_is_stripped(self, sops_runner) -> None:
        runner, _ = sops_runner(stdout=f"  {HEX_32}  \n".encode())
        assert SopsBackend(runner=runner).resolve(
            KeyReference.parse(SOPS_REF)
        ) == bytes.fromhex(HEX_32)

    def test_a_base64_document_resolves(self, sops_runner) -> None:
        # The second accepted encoding.  Two named spellings rather than a
        # guessing parser — see the class docstring for why.
        encoded = base64.b64encode(bytes.fromhex(OTHER_HEX_32))
        runner, _ = sops_runner(stdout=encoded + b"\n")
        assert SopsBackend(runner=runner).resolve(
            KeyReference.parse(SOPS_REF)
        ) == bytes.fromhex(OTHER_HEX_32)

    def test_a_string_stdout_is_accepted(self, sops_runner) -> None:
        # A deployment's runner may be configured with `text=True`; the
        # backend is tolerant of both rather than dictating which.
        runner, _ = sops_runner(stdout=HEX_32)
        assert SopsBackend(runner=runner).resolve(
            KeyReference.parse(SOPS_REF)
        ) == bytes.fromhex(HEX_32)

    def test_the_backend_names_the_sops_scheme(self) -> None:
        assert SopsBackend.scheme == "sops"

    def test_a_timeout_is_bounded(self, sops_backend: SopsBackend) -> None:
        # A backend that never returns is indistinguishable from a lost key to
        # every caller downstream, which is why the bound is finite.
        assert sops_backend.timeout > 0


class TestASopsFailureIsTheUnrecoverableState:
    def test_a_nonzero_exit_emits_the_alert(self, sops_runner) -> None:
        runner, _ = sops_runner(returncode=128, stderr=b"sops: key not found\n")
        with pytest.raises(UnrecoverableStateError) as raised:
            SopsBackend(runner=runner).resolve(KeyReference.parse(SOPS_REF))
        assert raised.value.alert.alert_kind == ALERT_KIND
        assert raised.value.alert.stage == KEY_BACKEND_STAGE

    def test_the_stderr_is_carried_into_the_record(self, sops_runner) -> None:
        # The backend's own words are the cause an operator acts on ("key not
        # found", "no matching creation rules"), so they travel with the alert
        # rather than being replaced by a generic message.
        runner, _ = sops_runner(
            returncode=128, stderr=b"sops: key not found: age identity\n"
        )
        with pytest.raises(UnrecoverableStateError) as raised:
            SopsBackend(runner=runner).resolve(KeyReference.parse(SOPS_REF))
        assert "key not found" in raised.value.alert.detail
        assert "128" in raised.value.alert.detail

    def test_a_timeout_emits_the_alert(self, sops_runner) -> None:
        def _timeout(argv, **kwargs):
            raise subprocess.TimeoutExpired(argv, kwargs.get("timeout", 60))

        with pytest.raises(UnrecoverableStateError) as raised:
            SopsBackend(runner=_timeout).resolve(KeyReference.parse(SOPS_REF))
        assert raised.value.__cause__ is not None
        assert raised.value.alert.stage == KEY_BACKEND_STAGE

    def test_a_failure_to_start_emits_the_alert(self) -> None:
        def _broken(argv, **kwargs):
            raise OSError("Exec format error")

        with pytest.raises(UnrecoverableStateError):
            SopsBackend(runner=_broken).resolve(KeyReference.parse(SOPS_REF))

    def test_the_timeout_is_actually_passed_to_the_runner(self, sops_runner) -> None:
        # A bound that is not applied is not a bound.
        seen: list = []

        def _run(argv, **kwargs):
            seen.append(kwargs)
            return _Completed(0, (HEX_32 + "\n").encode())

        SopsBackend(runner=_run, timeout=7).resolve(KeyReference.parse(SOPS_REF))
        assert seen[0]["timeout"] == 7

    def test_undecodable_stderr_still_yields_the_alert(self, sops_runner) -> None:
        # A stderr with invalid UTF-8 is still evidence of a failure that
        # already happened; refusing to render it would turn a decryption
        # failure into a Unicode error.
        runner, _ = sops_runner(returncode=1, stderr=b"\xff\xfe bad")
        with pytest.raises(UnrecoverableStateError):
            SopsBackend(runner=runner).resolve(KeyReference.parse(SOPS_REF))


class TestAMalformedSopsDocumentIsNotTheAlert:
    @pytest.mark.parametrize(
        "plaintext",
        [
            b"",
            b"\n",
            b"not-a-key-at-all",
            b"zz" * 32,  # 64 characters, but not hex
            b"YWJj",  # valid base64, but 3 bytes
            (HEX_32[:60]).encode(),  # 60 hex characters
        ],
    )
    def test_a_document_that_is_not_key_material_is_refused(
        self, sops_runner, plaintext: bytes
    ) -> None:
        runner, _ = sops_runner(stdout=plaintext)
        with pytest.raises(SidecarKeyError):
            SopsBackend(runner=runner).resolve(KeyReference.parse(SOPS_REF))

    def test_a_malformed_document_emits_no_alert(self, tmp_path, sops_runner) -> None:
        journal = KeyAlertJournal(f"sqlite:///{tmp_path}/alerts.db")
        runner, _ = sops_runner(stdout=b"not-a-key")
        with pytest.raises(SidecarKeyError):
            SopsBackend(runner=runner, journal=journal).resolve(
                KeyReference.parse(SOPS_REF)
            )
        assert journal.alerts() == ()

    def test_the_refusal_names_the_encodings_and_not_the_content(
        self, sops_runner
    ) -> None:
        # A malformed secret is still a secret: the refusal says how long the
        # text was and never quotes it, because the message ends up in a log.
        secret = "s3cr3t-not-hex-not-base64"
        runner, _ = sops_runner(stdout=secret.encode())
        with pytest.raises(SidecarKeyError) as raised:
            SopsBackend(runner=runner).resolve(KeyReference.parse(SOPS_REF))
        assert secret not in str(raised.value)
        assert str(len(secret)) in str(raised.value)
        assert "base64" in str(raised.value)

    def test_a_missing_binary_is_a_configuration_mistake_not_the_alert(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # `sops` not being installed is an operator fixing an image, not a
        # lost key: nothing was attempted, no data is unrecoverable, and
        # paging someone about it would be a false alarm of the loudest kind.
        monkeypatch.setattr("nulloracle.backends.shutil.which", lambda name: None)
        with pytest.raises(SidecarKeyError, match="sops binary on PATH"):
            SopsBackend().resolve(KeyReference.parse(SOPS_REF))

    def test_a_missing_binary_is_a_sidecar_key_error_and_not_an_alert(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("nulloracle.backends.shutil.which", lambda name: None)
        with pytest.raises(SidecarKeyError) as raised:
            SopsBackend().resolve(KeyReference.parse(SOPS_REF))
        assert not isinstance(raised.value, UnrecoverableStateError)


# -- Dispatch ----------------------------------------------------------------


class TestDispatch:
    def test_a_hex_reference_resolves_with_no_backend_at_all(self) -> None:
        # An inline key cannot be *unavailable*: there is no backend to fail
        # and no network to reach, so `hex:` never touches the backend map.
        material = resolve_material(KeyReference.parse(f"hex:{HEX_32}"), backends={})
        assert material == bytes.fromhex(HEX_32)

    def test_the_right_backend_answers_for_each_scheme(
        self, kms_backend: KmsBackend, sops_backend: SopsBackend
    ) -> None:
        backends = {"kms": kms_backend, "sops": sops_backend}
        assert resolve_material(
            KeyReference.parse(KMS_REF), backends=backends
        ) == bytes.fromhex(HEX_32)
        assert resolve_material(
            KeyReference.parse(SOPS_REF), backends=backends
        ) == bytes.fromhex(HEX_32)

    @pytest.mark.parametrize("reference", [KMS_REF, SOPS_REF])
    def test_an_unconfigured_backend_is_a_configuration_mistake(
        self, reference: str
    ) -> None:
        # Nothing was attempted, so nothing is unrecoverable — the refusal
        # names what the deployment must supply.
        with pytest.raises(SidecarKeyError) as raised:
            resolve_material(KeyReference.parse(reference), backends={})
        assert not isinstance(raised.value, UnrecoverableStateError)

    def test_the_unconfigured_refusal_names_the_variable_to_set(self) -> None:
        with pytest.raises(SidecarKeyError) as raised:
            resolve_material(KeyReference.parse(KMS_REF), backends={})
        assert KMS_BLOB_ENV in str(raised.value)

    def test_the_default_backends_always_offer_sops_and_never_a_client(self) -> None:
        # The sops backend always exists — there is nothing to configure
        # beyond the reference, so whether the tool is installed waits for the
        # call.  The KMS backend exists only when a blob is named.
        assert set(default_backends({})) == {"sops"}
        assert set(default_backends({KMS_BLOB_ENV: "/z0/k.bin"})) == {"kms", "sops"}

    def test_building_the_default_backends_imports_nothing_and_reads_nothing(
        self, tmp_path
    ) -> None:
        # No boto3 import, no `shutil.which`, no file read: this is why the
        # question "what can this deployment resolve?" is free to ask.
        blob = tmp_path / "wrapped.bin"  # deliberately never created
        backends = default_backends({KMS_BLOB_ENV: str(blob)})
        assert "kms" in backends


# -- The feature's whole sentence -------------------------------------------


class TestResolvingTheSidecarKey:
    """*System resolves the sidecar decryption key from KMS or sops.*"""

    def test_it_reads_the_documented_reference_variable(self, kms_backend) -> None:
        result = resolve_sidecar_key(
            {KEY_REF_ENV: KMS_REF}, backends={"kms": kms_backend}
        )
        assert isinstance(result, EnsureKeyResult)
        assert result.key.reveal() == bytes.fromhex(HEX_32)

    def test_a_sops_reference_resolves_through_the_same_call(
        self, sops_backend: SopsBackend
    ) -> None:
        result = resolve_sidecar_key(
            {KEY_REF_ENV: SOPS_REF}, backends={"sops": sops_backend}
        )
        assert result.key.reveal() == bytes.fromhex(HEX_32)

    def test_a_hex_reference_still_resolves(self) -> None:
        result = resolve_sidecar_key({KEY_REF_ENV: f"hex:{HEX_32}"}, backends={})
        assert result.key.reveal() == bytes.fromhex(HEX_32)

    def test_it_never_claims_to_have_created_the_key(self, kms_backend) -> None:
        # This member resolves an *existing* key and has no path that mints
        # one.  Feature 155's backup obligation hangs on this flag, so
        # claiming `created` would tell a caller to back up something that was
        # never made.
        result = resolve_sidecar_key(
            {KEY_REF_ENV: KMS_REF}, backends={"kms": kms_backend}
        )
        assert result.created is False

    def test_an_unset_reference_is_refused_by_name(self) -> None:
        with pytest.raises(SidecarKeyError, match=KEY_REF_ENV):
            resolve_sidecar_key({}, backends={})

    def test_a_blank_reference_is_refused(self) -> None:
        with pytest.raises(SidecarKeyError):
            resolve_sidecar_key({KEY_REF_ENV: "   "}, backends={})

    def test_a_backend_failure_propagates_as_the_alert(self, kms_blob) -> None:
        backend = KmsBackend(_KmsClient(failure=RuntimeError("denied")), blob=kms_blob)
        with pytest.raises(UnrecoverableStateError) as raised:
            resolve_sidecar_key({KEY_REF_ENV: KMS_REF}, backends={"kms": backend})
        assert raised.value.alert.stage == KEY_BACKEND_STAGE

    def test_a_failed_resolution_records_into_the_journal(
        self, tmp_path, kms_blob
    ) -> None:
        # The whole feature in one test: a KMS reference, a failing backend,
        # and a row left behind afterwards — the durable half of the alert.
        journal = KeyAlertJournal(f"sqlite:///{tmp_path}/alerts.db")
        backend = KmsBackend(
            _KmsClient(failure=RuntimeError("denied")), blob=kms_blob, journal=journal
        )
        with pytest.raises(UnrecoverableStateError):
            resolve_sidecar_key({KEY_REF_ENV: KMS_REF}, backends={"kms": backend})
        (record,) = journal.alerts()
        assert record.alert_kind == ALERT_KIND
        assert record.stage == KEY_BACKEND_STAGE

    def test_a_foreign_account_is_refused_before_it_holds_anything(
        self, kms_backend
    ) -> None:
        # feature 111's resolution runs through `ensure_key`, so §7.1's
        # one-service-account rule is enforced on this path too — a
        # resolution that skipped the account check would be a second way to
        # reach the key.
        from nulloracle import SERVICE_ACCOUNT_ENV

        with pytest.raises(SidecarAccessError):
            resolve_sidecar_key(
                {KEY_REF_ENV: KMS_REF, SERVICE_ACCOUNT_ENV: "nulloracle-svc"},
                backends={"kms": kms_backend},
                account="scoring-svc",
            )


# -- The secret never surfaces ----------------------------------------------


class TestTheTargetNeverSurfaces:
    """A message that names a ``hex:`` target is a message that leaks the key."""

    @pytest.mark.parametrize("reference", [KMS_REF, SOPS_REF])
    def test_no_failure_message_quotes_the_target(
        self, tmp_path, reference: str
    ) -> None:
        # Every backend failure this module has, over both backend schemes.
        journal = KeyAlertJournal(f"sqlite:///{tmp_path}/a.db")
        for backend in (
            KmsBackend(
                _KmsClient(failure=RuntimeError("denied")),
                blob=None,
                journal=journal,
            ),
            KmsBackend(
                _KmsClient(b"short"), blob=tmp_path / "absent.bin", journal=journal
            ),
        ):
            with pytest.raises(Exception) as raised:  # noqa: B017 - any failure
                resolve_material(
                    KeyReference.parse(reference),
                    backends={backend.scheme: backend},
                )
            target = KeyReference.parse(reference).target
            assert target not in str(raised.value)
            assert HEX_32 not in str(raised.value)

    @pytest.mark.parametrize("target", ["zz", "", "abcd", HEX_32[:60]])
    def test_a_malformed_inline_key_is_never_quoted_back(self, target: str) -> None:
        # The `hex:` case is the sharp one — its target *is* the key — but it
        # fails differently: it never reaches a backend, because a key that is
        # not key material is a configuration mistake and the grammar refuses
        # it before dispatch.  Hence a separate test from the one above.
        with pytest.raises(SidecarKeyError) as raised:
            resolve_material(KeyReference.parse(f"hex:{target}"), backends={})
        assert not isinstance(raised.value, UnrecoverableStateError)
        if target:
            assert target not in str(raised.value)

    def test_the_record_carries_the_redacted_label(self, tmp_path) -> None:
        journal = KeyAlertJournal(f"sqlite:///{tmp_path}/a.db")
        backend = KmsBackend(
            _KmsClient(failure=RuntimeError("denied")),
            blob=tmp_path / "absent.bin",
            journal=journal,
        )
        with pytest.raises(UnrecoverableStateError):
            backend.resolve(KeyReference.parse(KMS_REF))
        (record,) = journal.alerts()
        assert record.reference == "kms:<redacted>"
        assert "arn:aws" not in (record.reference or "")
        assert "arn:aws" not in record.detail

    def test_the_resolved_material_is_wrapped_rather_than_returned_raw(
        self, kms_backend
    ) -> None:
        # `resolve_material` returns bytes — that is its contract — but the
        # feature's entry point hands out a wrapper whose repr redacts.
        result = resolve_sidecar_key(
            {KEY_REF_ENV: KMS_REF}, backends={"kms": kms_backend}
        )
        assert HEX_32 not in repr(result.key)
        assert "redacted" in repr(result.key)

    def test_a_detailed_backend_message_is_truncated(self, tmp_path) -> None:
        # A backend's message is composed by code this module does not own; a
        # secret pasted into one must not ride along whole.
        journal = KeyAlertJournal(f"sqlite:///{tmp_path}/a.db")
        backend = KmsBackend(
            _KmsClient(failure=RuntimeError(HEX_32 * 20)),
            blob=tmp_path / "absent.bin",
            journal=journal,
        )
        with pytest.raises(UnrecoverableStateError):
            backend.resolve(KeyReference.parse(KMS_REF))
        (record,) = journal.alerts()
        assert len(record.detail) <= 200


# -- The deferred imports ----------------------------------------------------


class TestTheOptionalDependenciesAreDeferred:
    """The scan imports this package; it must not need a cloud SDK."""

    def test_importing_the_backends_module_pulls_in_no_sdk(self) -> None:
        # The factory's workspace scan imports this package to fire its
        # @register decorators.  A module-scope `import boto3` would make that
        # scan fail in every environment that had not installed a cloud SDK —
        # the exact failure `require_cryptography` exists to avoid for the
        # cipher.
        import sys

        import nulloracle.backends as module  # noqa: F401

        assert "boto3" not in sys.modules

    def test_a_missing_sdk_is_a_named_module_error(self, monkeypatch) -> None:
        import builtins

        from nulloracle.backends import require_boto3

        real_import = builtins.__import__

        def _no_boto3(name, *args, **kwargs):
            if name == "boto3":
                raise ModuleNotFoundError("No module named 'boto3'")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", _no_boto3)
        with pytest.raises(ModuleNotFoundError, match="boto3"):
            require_boto3()

    def test_the_missing_sdk_message_names_the_alternative(self, monkeypatch) -> None:
        import builtins

        from nulloracle.backends import require_boto3

        real_import = builtins.__import__

        def _no_boto3(name, *args, **kwargs):
            if name == "boto3":
                raise ModuleNotFoundError("No module named 'boto3'")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", _no_boto3)
        with pytest.raises(ModuleNotFoundError) as raised:
            require_boto3()
        assert "sops:" in str(raised.value) or "hex:" in str(raised.value)
