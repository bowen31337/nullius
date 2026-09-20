"""Feature 111, end to end: the assembled system resolves the key, and alerts.

app_spec.xml, "Null Oracle & Planted Nulls", feature 111: *System resolves the
sidecar decryption key from KMS or sops, which emits an unrecoverable_state
alert when decryption fails.*

The member's own suite (``packages/nulloracle/tests``) pins each contract in
isolation — the backends, the record, the journal, the builder.  This suite
pins the sentence those contracts are *for*, through the assembled system: the
component the application factory composes, the environment a deployment
actually sets, a real sealed sidecar, and a key reference that resolves through
a real backend seam.

That distinction is load-bearing here in a way it is not for a purely internal
feature.  §7's row — *Null sidecar key lost → Decrypt failure → Unrecoverable* —
is a claim about the **running system**: that a process which cannot obtain the
key does not quietly carry on computing over nulls whose labels it can no longer
read.  A member that passed its unit suite while the composed application
carried no journal and never emitted the alert would satisfy every test in that
suite and fail exactly these.

Three integration questions, then:

* **does the composed system carry the journal**, at the location a deployment
  names, degrading to nothing when it names none?
* **does a resolution failure produce the alert**, end to end — the exception
  raised *and* the row on disk, in the same database the rest of the workspace
  uses?
* **does a real sealed sidecar open under a resolved key**, so that the
  resolution path this feature adds is the one feature 109's sealing path
  actually consumes?  A resolution that returned the wrong bytes would pass
  every unit test in the member suite and make every sidecar in the deployment
  unopenable.
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from app.module_loader import create_app

from nulloracle import (
    ALERT_KIND,
    DATABASE_URL_ENV,
    KEY_REF_ENV,
    KEY_BACKEND_STAGE,
    SIDECAR_STAGE,
    KeyReference,
    KmsBackend,
    NullAssignment,
    NullSidecar,
    SopsBackend,
    SidecarKey,
    UnrecoverableStateError,
    emit_unrecoverable_state,
    guard_decryption,
    load_key_alerts,
    resolve_sidecar_key,
)

COMPONENT_NAME = "nulloracle-sidecar-key-alert"
SIDECAR_COMPONENT_NAME = "nulloracle"

#: The key the sidecars in this file are sealed under, and the key a resolving
#: backend hands back when it is working.
SEALING_KEY_HEX = "0f" * 32
#: A different, equally valid key — what a *broken* resolution returns, and the
#: difference between "the system resolved the key" and "the system resolved
#: *a* key".
WRONG_KEY_HEX = "cd" * 32

KMS_REF = "kms:arn:aws:kms:eu-west-1:1234:key/sidecar"


# -- Fakes -------------------------------------------------------------------


class _KmsClient:
    """A KMS client returning ``plaintext``, or raising ``failure``."""

    def __init__(self, plaintext: bytes = b"", *, failure=None) -> None:
        self._plaintext = plaintext
        self._failure = failure
        self.calls: list[dict] = []

    def decrypt(self, **kwargs):
        self.calls.append(kwargs)
        if self._failure is not None:
            raise self._failure
        return {"Plaintext": self._plaintext}


class _Completed:
    def __init__(self, returncode=0, stdout=b"", stderr=b"") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


@pytest.fixture
def composed_journal(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """The journal the *composed application* carries for this environment.

    Read out of the application the factory builds — not constructed directly —
    because the claim is about the assembled system: a deployment sets
    ``DATABASE_URL`` and the composed application must carry a journal writing
    to it.  The root conftest already points ``DATABASE_URL`` at a per-test
    database, so this is the same store the rest of the workspace uses.
    """
    return create_app().get(COMPONENT_NAME)


@pytest.fixture
def wrapped_blob(tmp_path: Path) -> Path:
    """The KMS-wrapped data key the backend feeds to ``Decrypt``.

    A real file rather than raw bytes: ``CiphertextBlob`` is whatever the KMS
    produced when it wrapped the data key, and a deployment stores it.  The
    bytes are opaque here — this member never inspects them, the KMS does.
    """
    blob = tmp_path / "wrapped-data-key.bin"
    blob.write_bytes(b"wrapped-by-the-kms")
    return blob


@pytest.fixture
def sealed_sidecar(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """A real sidecar sealed under :data:`SEALING_KEY_HEX`, plus its assignment.

    Modes are set explicitly: §7.1's gate checks both the file's mode and its
    directory's, and a sidecar it refuses would raise an access error — a
    different failure, reached before the cipher runs, and one that would make
    these tests pass or fail for the wrong reason.
    """
    path = tmp_path / "z0" / "null" / "sidecar.enc"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.parent.chmod(0o700)
    monkeypatch.setenv("NULL_SIDECAR_PATH", str(path))
    node_id = str(uuid.uuid4())
    NullSidecar(path, SidecarKey.from_hex(SEALING_KEY_HEX)).write(
        [NullAssignment(node_id=node_id, is_null=True, perm_seed=11)]
    )
    path.chmod(0o600)
    return path, node_id


# -- The composed system carries the journal ---------------------------------


class TestTheComposedSystemCarriesTheJournal:
    def test_the_factory_composes_a_journal_for_the_environment(
        self, composed_journal
    ) -> None:
        assert composed_journal is not None

    def test_the_journal_the_factory_composed_actually_works(
        self, composed_journal, test_database_url: str
    ) -> None:
        # Composed *and* usable: an empty stand-in would satisfy the test above.
        assert composed_journal.alerts() == ()
        emit_unrecoverable_state(
            KEY_BACKEND_STAGE, reference=KMS_REF, detail="the KMS refused",
            journal=composed_journal,
        )
        assert len(load_key_alerts(test_database_url)) == 1

    def test_an_unconfigured_deployment_composes_no_journal(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Degrade, don't break — and note this costs *durability*, not the
        # alert: the emission works with `journal=None`, which is why the
        # component's absence is survivable and its presence is not required.
        monkeypatch.delenv(DATABASE_URL_ENV, raising=False)
        assert create_app().get(COMPONENT_NAME) is None

    def test_the_alert_still_emits_with_no_journal_composed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # The claim that makes the absence acceptable, asserted end to end.
        monkeypatch.delenv(DATABASE_URL_ENV, raising=False)
        assert create_app().get(COMPONENT_NAME) is None
        # `emit_unrecoverable_state` *returns* the error rather than raising it
        # — the caller holds the failure that caused this one and is the one
        # that can chain it — so the assertion is on what came back.
        alert = emit_unrecoverable_state(
            SIDECAR_STAGE, detail="the tag did not verify"
        )
        assert isinstance(alert, UnrecoverableStateError)
        assert alert.alert.alert_kind == ALERT_KIND

    def test_composition_does_not_emit_an_alert(
        self, test_database_url: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # A KMS reference is configured and pointed at a backend that would
        # fail — and composing the application must record nothing.  §7's alert
        # is emitted by a process that *decided* to need the key; a builder
        # that resolved it would raise one alert per `create_app()`, in
        # deployments that never asked.
        monkeypatch.setenv(KEY_REF_ENV, KMS_REF)
        app = create_app()
        assert app.get(COMPONENT_NAME) is not None
        assert load_key_alerts(test_database_url) == ()


# -- The feature's sentence, through the assembled system --------------------


class TestResolvingThroughTheComposedSystem:
    def test_a_kms_reference_resolves_and_opens_the_sidecar(
        self, sealed_sidecar, composed_journal, wrapped_blob
    ) -> None:
        # The whole chain in one test: a real sealed sidecar, a `kms:`
        # reference, a backend that unwraps the sealing key, and the labels
        # read back.  This is the claim a unit test cannot make — that the key
        # feature 111 resolves is the key feature 109 *used*.
        path, node_id = sealed_sidecar
        client = _KmsClient(bytes.fromhex(SEALING_KEY_HEX))
        result = resolve_sidecar_key(
            {KEY_REF_ENV: KMS_REF},
            backends={"kms": KmsBackend(client, blob=wrapped_blob)},
        )
        assert result.key.reveal() == bytes.fromhex(SEALING_KEY_HEX)
        assert client.calls[0]["KeyId"] == "arn:aws:kms:eu-west-1:1234:key/sidecar"

        labels = NullSidecar(path, result.key).open()
        assert labels[node_id].is_null is True

    def test_a_sops_reference_resolves_and_opens_the_sidecar(
        self, sealed_sidecar
    ) -> None:
        # The other scheme, through the same entry point — the spec's "from
        # KMS **or** sops" being a claim about one call, not two.
        path, node_id = sealed_sidecar
        result = resolve_sidecar_key(
            {KEY_REF_ENV: "sops:/z0/null/key.enc.yaml"},
            backends={
                "sops": SopsBackend(
                    runner=lambda argv, **kw: _Completed(
                        0, (SEALING_KEY_HEX + "\n").encode()
                    )
                )
            },
        )
        assert NullSidecar(path, result.key).open()[node_id].is_null is True

    def test_a_hex_reference_still_resolves_with_no_backend(
        self, sealed_sidecar
    ) -> None:
        # The pre-111 path is untouched: an inline key resolves with no
        # backend configured at all, so this feature adds a capability rather
        # than replacing one.
        path, node_id = sealed_sidecar
        result = resolve_sidecar_key({KEY_REF_ENV: f"hex:{SEALING_KEY_HEX}"})
        assert NullSidecar(path, result.key).open()[node_id].is_null is True

    def test_the_resolution_never_claims_to_have_created_the_key(
        self, composed_journal, wrapped_blob
    ) -> None:
        # Feature 155's backup obligation hangs on this flag; a resolution
        # that reported `created` would tell an operator to back up a key this
        # member never made.
        result = resolve_sidecar_key(
            {KEY_REF_ENV: KMS_REF},
            backends={"kms": KmsBackend(
                _KmsClient(bytes.fromhex(SEALING_KEY_HEX)), blob=wrapped_blob
            )},
        )
        assert result.created is False

    def test_a_resolution_that_returns_the_wrong_key_leaves_the_sidecar_shut(
        self, sealed_sidecar, wrapped_blob
    ) -> None:
        # The failure this guards against is subtle: a backend that returns
        # *a* key rather than *the* key resolves successfully and opens
        # nothing.  §7's row is about the key being gone, so this is the
        # sidecar stage — and it must be distinguishable from the backend
        # stage, because the two send an operator to different places.
        path, _ = sealed_sidecar
        result = resolve_sidecar_key(
            {KEY_REF_ENV: KMS_REF},
            backends={"kms": KmsBackend(
                _KmsClient(bytes.fromhex(WRONG_KEY_HEX)), blob=wrapped_blob
            )},
        )
        with pytest.raises(Exception, match="authentication|tag|decrypt"):
            NullSidecar(path, result.key).open()


# -- The alert, end to end ---------------------------------------------------


class TestTheAlertThroughTheComposedSystem:
    def test_a_failing_backend_raises_the_alert_and_records_it(
        self, composed_journal, test_database_url: str
    ) -> None:
        # *"which emits an unrecoverable_state alert when decryption fails"* —
        # the feature's sentence, through the assembled system: the composed
        # journal, a real failure, and both halves of the emission checked.
        client = _KmsClient(
            failure=RuntimeError("AccessDeniedException: grant revoked")
        )
        with pytest.raises(UnrecoverableStateError) as raised:
            resolve_sidecar_key(
                {KEY_REF_ENV: KMS_REF},
                backends={
                    "kms": KmsBackend(client, blob=None, journal=composed_journal)
                },
            )
        assert raised.value.alert.alert_kind == ALERT_KIND
        assert raised.value.alert.stage == KEY_BACKEND_STAGE

        (record,) = load_key_alerts(test_database_url)
        assert record.alert_kind == ALERT_KIND
        assert record == raised.value.alert

    def test_the_recorded_alert_holds_the_redacted_reference(
        self, composed_journal, test_database_url: str
    ) -> None:
        # The alert is a row in a database an operator sweeps; the reference it
        # names must be the label, never the target.
        client = _KmsClient(failure=RuntimeError("denied"))
        with pytest.raises(UnrecoverableStateError):
            resolve_sidecar_key(
                {KEY_REF_ENV: KMS_REF},
                backends={
                    "kms": KmsBackend(client, blob=None, journal=composed_journal)
                },
            )
        (record,) = load_key_alerts(test_database_url)
        assert record.reference == "kms:<redacted>"
        assert "arn:aws" not in repr(record)

    def test_a_tampered_sidecar_emits_the_alert_through_the_guard(
        self, sealed_sidecar, composed_journal, test_database_url: str
    ) -> None:
        # The other half of §7's row: the key resolved, the file did not open.
        # A real sidecar, sealed under one key and opened under another, so the
        # tag failure is a genuine one rather than a fabricated exception.
        path, _ = sealed_sidecar
        with pytest.raises(UnrecoverableStateError) as raised:
            with guard_decryption(
                reference=KeyReference.parse(KMS_REF), journal=composed_journal
            ):
                NullSidecar(path, SidecarKey.from_hex(WRONG_KEY_HEX)).open()
        assert raised.value.alert.stage == SIDECAR_STAGE
        (record,) = load_key_alerts(test_database_url)
        assert record.stage == SIDECAR_STAGE
        assert record.reference == "kms:<redacted>"

    def test_a_clean_open_through_the_guard_records_nothing(
        self, sealed_sidecar, composed_journal, test_database_url: str
    ) -> None:
        # The guard must be invisible on the happy path: a journal that
        # recorded on every open would be noise an operator learns to ignore,
        # which is the failure mode an alerting system dies of.
        path, node_id = sealed_sidecar
        with guard_decryption(journal=composed_journal):
            labels = NullSidecar(path, SidecarKey.from_hex(SEALING_KEY_HEX)).open()
        assert labels[node_id].is_null is True
        assert load_key_alerts(test_database_url) == ()

    def test_a_broken_database_does_not_hide_the_alert(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # The integration shape of the "the journal is not a gate" promise: a
        # deployment whose DATABASE_URL is a scheme this store cannot speak
        # *composes* a journal (the URL is inspected on first use, so
        # composition survives — asserted elsewhere), and every emission must
        # still arrive as §7's alert rather than as a storage error.  This is
        # the case where an operator most needs to be told the key is gone,
        # because the database is already unhealthy.
        monkeypatch.setenv(DATABASE_URL_ENV, "postgresql://db.internal/nullius")
        journal = create_app().get(COMPONENT_NAME)
        assert journal is not None

        client = _KmsClient(failure=RuntimeError("AccessDeniedException"))
        with pytest.raises(UnrecoverableStateError) as raised:
            resolve_sidecar_key(
                {KEY_REF_ENV: KMS_REF},
                backends={
                    "kms": KmsBackend(client, blob=None, journal=journal)
                },
            )
        assert raised.value.alert.alert_kind == ALERT_KIND
        assert raised.value.persistence_failure is not None

    def test_a_malformed_secret_records_nothing(
        self, composed_journal, test_database_url: str, wrapped_blob
    ) -> None:
        # The distinction the feature rests on, at the integration level: a
        # mistyped reference is a configuration mistake whose repair is not a
        # restore, so it must not page anyone.
        from nulloracle import SidecarKeyError

        with pytest.raises(SidecarKeyError):
            resolve_sidecar_key(
                {KEY_REF_ENV: KMS_REF},
                backends={"kms": KmsBackend(_KmsClient(b"short"), blob=wrapped_blob)},
            )
        assert load_key_alerts(test_database_url) == ()

    def test_the_alert_survives_the_process_that_found_it(
        self, test_database_url: str
    ) -> None:
        # The point of persisting at all: a *second* process — here, a fresh
        # composition reading the same database — sees the state the first one
        # recorded.  This is what §7 means by not letting it pass unnoticed.
        first = create_app().get(COMPONENT_NAME)
        emit_unrecoverable_state(
            SIDECAR_STAGE, reference=KMS_REF, detail="the tag", journal=first
        )
        second = create_app().get(COMPONENT_NAME)
        assert second.latest().stage == SIDECAR_STAGE

    def test_repeated_failures_accumulate_rather_than_collapse(
        self, composed_journal, test_database_url: str
    ) -> None:
        # A process that restarts and fails again is two observations of one
        # state, and the span between them is how long the deployment has been
        # in it — the datum an operator choosing between a restore and a
        # rebuild reads.  Collapsing them would destroy it.
        for _ in range(3):
            emit_unrecoverable_state(
                KEY_BACKEND_STAGE, reference=KMS_REF, detail="denied",
                journal=composed_journal,
            )
        assert len(load_key_alerts(test_database_url)) == 3
