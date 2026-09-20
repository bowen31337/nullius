"""KMS and sops: the two backends feature 111 resolves the sidecar key from.

app_spec.xml, "Null Oracle & Planted Nulls", feature 111: *System resolves
the sidecar decryption key from KMS or sops, which emits an unrecoverable_state
alert when decryption fails.*  docs/nullius-tech-architecture.md §7.1 fixes
where the key lives — ``sidecar.enc  # AES-GCM, key in KMS/sops`` — and §18
states the rest of the rule: *"Null sidecar key in KMS or ``sops``, granted to
exactly one service account, with access audit-logged."*

:mod:`nulloracle.keyref` owns the *grammar*: ``NULL_SIDECAR_KEY_REF`` parses
into a :class:`~nulloracle.keyref.KeyReference` whose scheme is ``kms``,
``sops`` or ``hex``, and everything that is not one of the three is refused by
name.  That module deliberately stops there, and says so twice — once in its
docstring (*"it deliberately does not call a KMS API or shell out to sops"*)
and once in :func:`~nulloracle.keyref.resolve_key`'s refusal, which names the
seam: *"resolve the material in that backend and pass it to ensure_key()"*.
This module is the backend side of that seam.  ``keyref`` is not modified and
its refusals are not relaxed; the two halves compose through
:func:`resolve_sidecar_key`, which consumes :func:`~nulloracle.keyref.ensure_key`
exactly as that refusal instructs.

**Both backends are seams, not SDK calls, and that is the load-bearing design
decision.**  Neither ``boto3`` nor a ``sops`` binary is a dependency of this
workspace (``pyproject.toml`` declares ``cryptography`` and nothing else of the
kind), and neither is importable-or-present in the environment the test suite
runs in.  A member that imported ``boto3`` at module scope would break the
factory's scan — which imports this package to fire its ``@register``
decorators — in every environment that had not installed a cloud SDK, the exact
failure :func:`~nulloracle.envelope.require_cryptography` exists to avoid for
the cipher.  So the SDK import and the subprocess both sit behind a *seam*:
:class:`KmsBackend` takes any object exposing ``decrypt(CiphertextBlob=…)
-> {"Plaintext": bytes}``, and :class:`SopsBackend` takes any object shaped
like :func:`subprocess.run`.  Tests inject fakes and exercise every decision
this module makes — the dispatch, the blob handling, the failure classification,
the alert — without a network, a credential or a binary.  A deployment gets the
real ones by passing nothing: :func:`boto3_kms_client` and the default runner.

**The two schemes resolve differently, because the two secrets are different
shapes.**  A ``kms:`` reference names a *key* — the ``KeyId`` a ``Decrypt`` call
is made against — and the ciphertext that call unwraps is the deployment's
data key, which lives somewhere the reference does not name.  So the KMS path
needs a second piece of configuration, ``NULL_SIDECAR_KMS_BLOB``, naming the
file holding the KMS-wrapped 32-byte data key.  The obvious alternative —
calling ``GenerateDataKey`` and using what comes back — is not merely different,
it is *wrong*: a fresh data key per resolution would seal each campaign's
sidecar under a key no later process could recover, which is §7's unrecoverable
failure arrived at by design.  A ``sops:`` reference names a *document*, and the
whole of what it means is "decrypt this and the plaintext is the key", so the
sops path needs nothing beyond the path itself.

**A failed decryption is the alert; a malformed secret is not.**  This is the
feature's central distinction and it is the same one the member's whole error
taxonomy rests on.  The KMS call erroring out, the ``sops`` invocation exiting
non-zero, timing out, or not being installed at all — each means the key could
not be *obtained*, and §7's answer is the same for every one of them:
*Unrecoverable. All FDR history becomes uninterpretable*.  Those emit
:func:`~nulloracle.keyalert.emit_unrecoverable_state` and raise
:class:`~nulloracle.keyalert.UnrecoverableStateError` chained from the cause.  A
sops document that decrypts cleanly to something that is *not* 32 bytes of key
material, on the other hand, is an operator who pointed the reference at the
wrong document — a configuration mistake with a repair that is not a restore, so
it stays a :class:`~nulloracle.errors.SidecarKeyError` and raises no alert.  The
line is *"could the key be obtained?"*, and it is drawn once, here, rather than
re-derived at each call site.

**Nothing in this module ever logs, stores or renders the key.**  The reference
*target* is never read on any path that composes a message — the record carries
:attr:`KeyReference.scheme_label` (``kms:<redacted>``) — and the resolved
material goes straight into a :class:`~nulloracle.keyref.SidecarKey`, whose
``repr`` redacts.  §1 states the stake: the null labels' leak *"silently voids
every calibration number the system has ever produced, and you would not
notice."*
"""

from __future__ import annotations

import base64
import binascii
import os
import shutil
import subprocess
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Optional, Protocol

from .errors import SidecarKeyError
from .keyalert import (
    KEY_BACKEND_STAGE,
    KeyAlertJournal,
    emit_unrecoverable_state,
)
from .keyref import (
    SIDECAR_KEY_BYTES,
    EnsureKeyResult,
    KeyReference,
    ensure_key,
    resolve_key,
)

__all__ = [
    "KMS_BLOB_ENV",
    "KMS_SCHEME",
    "SOPS_SCHEME",
    "SOPS_TIMEOUT_SECONDS",
    "KmsBackend",
    "KeyBackend",
    "SopsBackend",
    "boto3_kms_client",
    "default_backends",
    "require_boto3",
    "require_sops",
    "resolve_material",
    "resolve_sidecar_key",
]

#: The two scheme names this module speaks.  Restated from
#: :data:`~nulloracle.keyref._SCHEMES` rather than imported privately: a backend
#: states which scheme it answers for, and the grammar module's set is the
#: authority on what a reference may *be*.
KMS_SCHEME = "kms"
SOPS_SCHEME = "sops"

#: The environment variable naming the file holding the KMS-wrapped data key.
#:
#: ``kms:<arn>`` names the *key*, and a ``Decrypt`` call needs a ciphertext as
#: well as a key.  The ciphertext is the deployment's wrapped data key, which is
#: its own artifact — a blob an operator produced once, with the KMS, and
#: backed up alongside the key (feature 155).  Named here rather than folded
#: into the reference because the reference grammar is closed and
#: ``keyref``'s docstring argues the case: a fourth spelling would be a second
#: place for "what a reference is" to be decided.  ``app_spec.xml``'s
#: prerequisites list documents ``NULL_SIDECAR_KEY_REF`` but no blob variable,
#: so this one is named by analogy with the rest of the workspace — the sidecar's
#: own ``NULL_SIDECAR_PATH`` is spelled the same way, for the same reason.
KMS_BLOB_ENV = "NULL_SIDECAR_KMS_BLOB"

#: How long a ``sops`` invocation may run before it is refused.
#:
#: A backend that hangs is the failure mode a timeout exists for, and the value
#: is deliberately finite: a resolution that never returns is indistinguishable
#: from a lost key to every caller downstream, and §7's whole point is that a
#: lost key must *surface*.  Sixty seconds is far more than a local sops
#: decryption needs and short enough that a wedged process does not wedge the
#: campaign that is waiting on it.
SOPS_TIMEOUT_SECONDS = 60


class KeyBackend(Protocol):
    """A scheme's resolver: the seam the backends are spoken through.

    :meth:`resolve` takes the parsed :class:`~nulloracle.keyref.KeyReference`
    and either returns the key material or raises.  The contract it must keep is
    the one feature 111's alert depends on:

    * a failure to *obtain* the key — a backend error, a timeout, a missing
      tool — emits the ``unrecoverable_state`` alert and raises
      :class:`~nulloracle.keyalert.UnrecoverableStateError`;
    * a secret that was obtained but is not key material raises
      :class:`~nulloracle.errors.SidecarKeyError` and emits nothing.

    A backend is the natural place to draw that line because it is the only code
    that can tell the two apart: it is what saw the call fail versus what holds
    the bytes that came back.
    """

    #: The scheme this backend answers for — ``"kms"`` or ``"sops"``.
    scheme: str

    def resolve(self, reference: KeyReference) -> bytes:
        """Return the key material ``reference`` names, or raise."""
        ...  # pragma: no cover - protocol declaration


def require_boto3() -> Any:
    """Import and return ``boto3``, or raise naming the fix.

    Deferred to first use, exactly as :func:`~nulloracle.envelope.
    require_cryptography` is and for the same stated reason: the factory's
    workspace scan imports this package to fire its ``@register`` decorators,
    and that scan must not require a cloud SDK to be installed in every
    environment the workspace is composed in — the test sandbox, the replay
    path, a single-machine deployment that keeps its key in ``sops``.

    A missing SDK raises :class:`ModuleNotFoundError` rather than a sidecar
    error: it is an environment problem, not a key problem, and the same
    distinction ``require_cryptography`` draws.  The caller that hits it is
    :func:`boto3_kms_client`, whose message is what a deployment reads.
    """
    try:
        import boto3
    except ModuleNotFoundError as exc:  # pragma: no cover - dependency is optional
        raise ModuleNotFoundError(
            "the sidecar key reference names a KMS backend, which needs the "
            "boto3 package to call; install it (`uv add boto3` in the "
            "deployment that uses a kms: reference) or point "
            "NULL_SIDECAR_KEY_REF at a sops: or hex: reference instead"
        ) from exc
    return boto3


def boto3_kms_client(env: Optional[Mapping[str, str]] = None) -> Any:
    """Build the real KMS client — the default :class:`KmsBackend` client.

    Constructed through boto3's own default chain rather than from anything this
    module reads: an AWS KMS client resolves its region, its credentials and its
    endpoint from the SDK's standard configuration, and a member that
    re-implemented that lookup would be a second, disagreeing copy of a
    credential path — the thing :mod:`nulloracle.keyref`'s docstring refuses to
    grow.  The client is the deployment's to configure; this function only
    avoids importing boto3 until a ``kms:`` reference actually needs it.
    """
    return require_boto3().client("kms")


class KmsBackend:
    """``kms:`` — unwrap the sidecar's data key with AWS KMS.

    Constructed with a *client* — anything exposing ``decrypt(CiphertextBlob=…)
    -> {"Plaintext": bytes}``, which is what boto3's KMS client is — and the
    path of the blob holding the KMS-wrapped data key.  Tests pass a fake client
    and a temporary blob; a deployment passes nothing and gets
    :func:`boto3_kms_client` plus the path ``NULL_SIDECAR_KMS_BLOB`` names.

    **The reference names the key, the blob holds the ciphertext, and the
    unwrapped plaintext *is* the sidecar key.**  That is the whole protocol:

    1. read the wrapped data key from the blob;
    2. ``Decrypt(KeyId=<the reference target>, CiphertextBlob=<the blob>)``;
    3. the returned ``Plaintext`` is the 32-byte AES-256-GCM key.

    Every failure inside that sequence is a failure to *obtain* the key, so
    every one of them emits ``unrecoverable_state``.  Deliberately not attempted:
    a fallback to a locally cached key, a retry loop, a default key.  §7's row
    exists because there is no repair for a lost key short of restoring it, and
    a silent fallback is how a deployment comes to compute an FDR over a world
    whose nulls have quietly become real.
    """

    scheme = KMS_SCHEME

    def __init__(
        self,
        client: Any,
        *,
        blob: Optional[str | os.PathLike[str]] = None,
        env: Optional[Mapping[str, str]] = None,
        journal: Optional[KeyAlertJournal] = None,
    ) -> None:
        self._client = client
        self._env = os.environ if env is None else env
        self._blob = Path(blob).expanduser() if blob is not None else None
        self._journal = journal

    @classmethod
    def resolve_from_env(
        cls,
        env: Optional[Mapping[str, str]] = None,
        *,
        journal: Optional[KeyAlertJournal] = None,
    ) -> Optional["KmsBackend"]:
        """The KMS backend this environment configures, or ``None``.

        ``None`` when ``NULL_SIDECAR_KMS_BLOB`` names nothing — the deployment
        has no wrapped data key to unwrap, so it has no KMS backend, the same
        discoverable-absence answer every store in this workspace gives.  The
        client is built on first use rather than here, so resolving the *set* of
        backends costs no SDK import and no network call.
        """
        source = os.environ if env is None else env
        blob = source.get(KMS_BLOB_ENV, "").strip()
        if not blob:
            return None
        return cls(_LazyClient(), blob=blob, env=source, journal=journal)

    @property
    def blob(self) -> Optional[Path]:
        """The path of the KMS-wrapped data key, or ``None`` when unnamed."""
        return self._blob

    def resolve(self, reference: KeyReference) -> bytes:
        """Unwrap the data key named by ``reference``, or emit the alert.

        The sequence is the one in the class docstring.  ``reference.target`` —
        the KMS key ARN or id — is the only field read, and it is never put into
        a message or a record; what an alert carries is
        :attr:`KeyReference.scheme_label`.
        """
        if self._blob is None:
            # A KmsBackend built by hand with no blob is a wiring mistake, and
            # it is a failure to *obtain* the key rather than a malformed
            # secret: there is nothing to unwrap, so nothing can be unwrapped.
            alert = emit_unrecoverable_state(
                KEY_BACKEND_STAGE,
                reference=reference,
                detail=(
                    f"the KMS backend holds no wrapped data-key blob: set "
                    f"{KMS_BLOB_ENV} to the file holding the KMS-wrapped key"
                ),
                journal=self._journal,
            )
            raise alert
        try:
            blob = self._blob.read_bytes()
        except OSError as exc:
            alert = emit_unrecoverable_state(
                KEY_BACKEND_STAGE,
                reference=reference,
                detail=(
                    f"the KMS-wrapped data key at {self._blob} could not be "
                    f"read: {exc}"
                ),
                journal=self._journal,
            )
            raise alert from exc
        try:
            response = self._client.decrypt(
                KeyId=reference.target, CiphertextBlob=blob
            )
            plaintext = response["Plaintext"]
        except Exception as exc:  # noqa: BLE001 - every KMS failure is the alert
            # Deliberately broad.  A KMS `decrypt` can fail as a `ClientError`
            # (the grant is gone, the key is disabled, the ciphertext is not
            # from this key), as a `BotoCoreError` (no credentials, no region,
            # no network), or as a `KeyError` from the response shape — and §7
            # does not care which: every one of them means the key could not be
            # obtained.  Narrowing this to a named exception would make the
            # alert's emission depend on which SDK version raised, which is
            # exactly the silent-miss the feature exists to prevent.
            alert = emit_unrecoverable_state(
                KEY_BACKEND_STAGE,
                reference=reference,
                detail=f"the KMS Decrypt call failed: {exc}",
                journal=self._journal,
            )
            raise alert from exc
        return _validated_material(plaintext, reference)


class _LazyClient:
    """A KMS client built on first use — the default for the env-built backend.

    Exists so :meth:`KmsBackend.resolve_from_env` can answer *is there a KMS
    backend here?* without importing boto3 or building a client: the question is
    about configuration, and paying an SDK import and a credential-chain
    resolution to answer it would make composing the application cost a network
    call — which is precisely what the factory's builders must not do.
    """

    def __init__(self) -> None:
        self._client: Any = None

    def decrypt(self, **kwargs: Any) -> Any:
        """Build the real client, then delegate."""
        if self._client is None:
            self._client = boto3_kms_client()
        return self._client.decrypt(**kwargs)


def require_sops() -> str:
    """Return the path to the ``sops`` binary, or raise naming the fix.

    Looked up through :func:`shutil.which` on every call rather than cached: a
    deployment that installs the binary while the process is running (a
    container whose entrypoint fetches it, an operator fixing an image) then
    starts working without a restart, and the lookup is a ``PATH`` scan against
    a handful of directories.  A missing binary raises
    :class:`~nulloracle.errors.SidecarKeyError` rather than the alert — see
    :meth:`SopsBackend.resolve` for why a missing tool is a configuration
    mistake while a failing decryption is not.
    """
    found = shutil.which("sops")
    if found is None:
        raise SidecarKeyError(
            "the sidecar key reference names a sops backend, which needs the "
            "sops binary on PATH; install it in the deployment that uses a "
            "sops: reference, or point NULL_SIDECAR_KEY_REF at a kms: or hex: "
            "reference instead"
        )
    return found


class SopsBackend:
    """``sops:`` — decrypt a SOPS document whose plaintext is the key.

    Constructed with a *runner* — anything shaped like :func:`subprocess.run`
    (``run(argv, capture_output=…, check=…)``) — and invoked as ``sops
    --decrypt <path>``.  Tests pass a fake runner; a deployment passes nothing
    and gets :mod:`subprocess` itself.

    **A missing binary is a configuration mistake; a failing decryption is the
    alert.**  The two are split deliberately and the split is the whole of this
    class's subtlety.  If ``sops`` is not installed, the reference cannot be
    resolved *yet* and an operator fixes it by installing the tool — no data is
    lost, nothing is unrecoverable, and an alert would page someone about a
    deployment that is merely misconfigured.  If ``sops`` *runs and fails* — a
    non-zero exit, a timeout — the document could not be decrypted, and the
    overwhelming cause of that is the age/PGP/KMS key behind it being
    unavailable, which is §7's row exactly.  So the former raises
    :class:`~nulloracle.errors.SidecarKeyError` and the latter emits
    ``unrecoverable_state``.

    **The plaintext is read as hex or base64, and nothing else.**  A sops
    document's plaintext arrives as text with a trailing newline (the shape an
    editor and a YAML block scalar both produce), so it is stripped; what
    remains must be either 64 hex characters or the base64 of 32 bytes.  Two
    named encodings rather than a guessing parser, because a parser that tried
    several would eventually load the wrong kind of secret — the argument
    :mod:`nulloracle.keyref` makes for refusing a bare string.  Anything else is
    a :class:`~nulloracle.errors.SidecarKeyError` naming both accepted forms,
    with the offending text's *length* rather than its content: a malformed
    secret is still a secret.
    """

    scheme = SOPS_SCHEME

    #: The program name invoked when a caller injected its own runner.  A fake
    #: runner never execs anything, so the argv it is handed is only ever
    #: inspected — and pinning the literal name keeps an injected backend's
    #: argv assertion stable without requiring the real binary to be installed.
    _INJECTED_EXECUTABLE = "sops"

    def __init__(
        self,
        *,
        runner: Any = None,
        executable: Optional[str] = None,
        env: Optional[Mapping[str, str]] = None,
        journal: Optional[KeyAlertJournal] = None,
        timeout: int = SOPS_TIMEOUT_SECONDS,
    ) -> None:
        self._runner = subprocess.run if runner is None else runner
        # A caller that injected a runner owns the invocation, so the PATH
        # lookup is skipped for it: the lookup exists to discover *whether the
        # real tool can be run*, and a fake runner neither needs nor should
        # require the real tool to be present.  The real path keeps it, which
        # is where the missing-binary refusal belongs.
        self._injected = runner is not None
        self._executable = executable
        self._env = os.environ if env is None else env
        self._journal = journal
        self._timeout = timeout

    @classmethod
    def resolve_from_env(
        cls,
        env: Optional[Mapping[str, str]] = None,
        *,
        journal: Optional[KeyAlertJournal] = None,
    ) -> "SopsBackend":
        """The sops backend — always available to try.

        Unlike the KMS backend there is nothing to configure beyond the
        reference itself, so this backend is always constructed and the
        question of whether ``sops`` exists is deferred to the call.  That
        deferral is what keeps composing the application free: a ``shutil.which``
        at build time would make composition fail on a host that had not
        installed a tool the deployment might never reference, and the
        *reference* is what decides whether sops is needed.
        """
        return cls(env=os.environ if env is None else env, journal=journal)

    @property
    def timeout(self) -> int:
        """How long a ``sops`` invocation may run, in seconds."""
        return self._timeout

    def _program(self) -> str:
        """The program to invoke: the configured one, the real one, or the literal.

        Three cases, in order of who decided.  An explicit ``executable`` wins —
        a deployment pinning an absolute path is stating a fact this member
        cannot discover.  Otherwise a *real* backend resolves the binary through
        :func:`require_sops`, which is where the missing-tool refusal belongs.
        An *injected* runner gets the literal name: it execs nothing, so the
        lookup would be asking the host a question about a process that will
        never run, and a test asserting on the argv it was handed would fail on
        a machine that merely lacked the tool.
        """
        if self._executable is not None:
            return self._executable
        if self._injected:
            return self._INJECTED_EXECUTABLE
        return require_sops()

    def resolve(self, reference: KeyReference) -> bytes:
        """Decrypt the document ``reference`` names, or emit the alert."""
        argv = [self._program(), "--decrypt", reference.target]
        try:
            completed = self._runner(
                argv, capture_output=True, check=False, timeout=self._timeout
            )
        except subprocess.TimeoutExpired as exc:
            alert = emit_unrecoverable_state(
                KEY_BACKEND_STAGE,
                reference=reference,
                detail=(
                    f"the sops decryption did not finish within "
                    f"{self._timeout}s; a backend that never returns is "
                    "indistinguishable from a lost key to every caller"
                ),
                journal=self._journal,
            )
            raise alert from exc
        except OSError as exc:
            alert = emit_unrecoverable_state(
                KEY_BACKEND_STAGE,
                reference=reference,
                detail=f"the sops decryption could not be started: {exc}",
                journal=self._journal,
            )
            raise alert from exc
        if completed.returncode != 0:
            alert = emit_unrecoverable_state(
                KEY_BACKEND_STAGE,
                reference=reference,
                detail=(
                    f"sops exited {completed.returncode}: "
                    f"{_stderr_of(completed)}"
                ),
                journal=self._journal,
            )
            raise alert
        return _material_from_document(completed.stdout, reference)


def _stderr_of(completed: Any) -> str:
    """A finished process's stderr as text, tolerant of bytes and of absence.

    A fake runner in a test may hand back ``str`` or ``bytes`` or nothing at
    all, and a real one hands back ``bytes`` unless ``text=True`` was passed.
    Decoding is deliberately forgiving: a stderr with undecodable bytes is still
    evidence of a failure that already happened, and refusing to render it would
    turn a decryption failure into a Unicode error.
    """
    stderr = getattr(completed, "stderr", None)
    if stderr is None:
        return "(no stderr)"
    if isinstance(stderr, (bytes, bytearray)):
        return stderr.decode("utf-8", errors="replace").strip() or "(empty stderr)"
    return str(stderr).strip() or "(empty stderr)"


def _validated_material(plaintext: Any, reference: KeyReference) -> bytes:
    """Check a backend's plaintext is exactly the key, or refuse by name.

    A backend that returned something of the wrong shape is a *configuration*
    failure — the reference points at the wrong key or the wrong blob — not the
    unrecoverable state, so this raises :class:`~nulloracle.errors.
    SidecarKeyError` and emits no alert.  The length is named because a 16-byte
    secret pasted into a KMS blob is a key-length mistake, which
    :data:`~nulloracle.keyref.SIDECAR_KEY_BYTES` documents accepting one length
    for.
    """
    if isinstance(plaintext, (bytearray, memoryview)):
        plaintext = bytes(plaintext)
    if not isinstance(plaintext, bytes):
        raise SidecarKeyError(
            f"the {reference.scheme_label} backend returned "
            f"{type(plaintext).__name__} rather than key bytes; a backend "
            "resolves key material, and anything else it hands back is the "
            "wrong artifact behind the reference"
        )
    if len(plaintext) != SIDECAR_KEY_BYTES:
        raise SidecarKeyError(
            f"the {reference.scheme_label} backend returned {len(plaintext)} "
            f"bytes; the sidecar key is {SIDECAR_KEY_BYTES} (AES-256-GCM), so "
            "this reference names the wrong key material — see "
            "nulloracle.keyref.SIDECAR_KEY_BYTES for why one length is "
            "accepted rather than two"
        )
    return plaintext


def _material_from_document(stdout: Any, reference: KeyReference) -> bytes:
    """Read a decrypted sops document's plaintext as key material, or refuse.

    Accepts 64 hex characters or the base64 of 32 bytes, after stripping
    surrounding whitespace — the newline an editor, a YAML block scalar or a
    ``sops`` write all leave behind.  The refusal names the *length* of what came
    back and never its content: a malformed secret is still a secret, and a
    message that quoted it would be the leak §1 is about.
    """
    text = _stdout_text(stdout).strip()
    if not text:
        raise SidecarKeyError(
            f"the {reference.scheme_label} document decrypted to nothing; an "
            "empty document names no key, and silently continuing would seal "
            "the sidecar under no material at all"
        )
    if len(text) == SIDECAR_KEY_BYTES * 2:
        try:
            return _validated_material(bytes.fromhex(text), reference)
        except ValueError:
            pass  # not hex after all; fall through to base64
    try:
        decoded = base64.b64decode(text, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise SidecarKeyError(
            f"the {reference.scheme_label} document decrypted to "
            f"{len(text)} characters that are neither {SIDECAR_KEY_BYTES * 2} "
            "hex characters nor the base64 of the key; a sops document for the "
            "sidecar holds the key in one of those two encodings, and this one "
            "holds something else (its content is deliberately not quoted — a "
            "malformed secret is still a secret)"
        ) from exc
    return _validated_material(decoded, reference)


def _stdout_text(stdout: Any) -> str:
    """A finished process's stdout as text, tolerant of bytes and of absence."""
    if stdout is None:
        return ""
    if isinstance(stdout, (bytes, bytearray)):
        return stdout.decode("utf-8", errors="replace")
    return str(stdout)


def default_backends(
    env: Optional[Mapping[str, str]] = None,
    *,
    journal: Optional[KeyAlertJournal] = None,
) -> dict[str, KeyBackend]:
    """The backends an environment configures, keyed by scheme.

    Always contains ``sops`` — there is nothing to configure beyond the
    reference, so the backend exists and the question of whether the tool is
    installed waits for the call.  Contains ``kms`` only when
    ``NULL_SIDECAR_KMS_BLOB`` names a wrapped data key, because without a
    ciphertext there is nothing for a ``Decrypt`` call to unwrap.

    Building this map performs no I/O: no SDK import, no ``which``, no file
    read.  That is what lets a caller ask *what can this deployment resolve?*
    without spending a network call to find out.
    """
    source = os.environ if env is None else env
    backends: dict[str, KeyBackend] = {
        SOPS_SCHEME: SopsBackend.resolve_from_env(source, journal=journal)
    }
    kms = KmsBackend.resolve_from_env(source, journal=journal)
    if kms is not None:
        backends[KMS_SCHEME] = kms
    return backends


def resolve_material(
    reference: KeyReference,
    *,
    backends: Optional[Mapping[str, KeyBackend]] = None,
    env: Optional[Mapping[str, str]] = None,
    journal: Optional[KeyAlertJournal] = None,
) -> bytes:
    """Resolve ``reference`` to key material, through the right backend.

    The dispatch: ``hex:`` resolves inline through
    :func:`~nulloracle.keyref.resolve_key` (no backend, no I/O, no alert — an
    inline key cannot be *unavailable*), ``kms:`` and ``sops:`` go to the
    backend that answers for their scheme.  A reference whose scheme has no
    configured backend is a configuration failure rather than the unrecoverable
    state, so it raises :class:`~nulloracle.errors.SidecarKeyError` naming what
    is missing — the distinction this module draws everywhere.

    ``backends`` defaults to :func:`default_backends`, and passing one is how a
    test or a deployment supplies a client or a runner.
    """
    if reference.scheme == "hex":
        return resolve_key(reference).reveal()
    available = default_backends(env, journal=journal) if backends is None else backends
    backend = available.get(reference.scheme)
    if backend is None:
        raise SidecarKeyError(
            f"the sidecar key reference {reference.scheme_label} names the "
            f"{reference.scheme!r} backend, which this deployment does not "
            "configure: a kms: reference needs "
            f"{KMS_BLOB_ENV} naming the KMS-wrapped data key, and a sops: "
            "reference needs the sops binary on PATH. Neither is a lost key — "
            "nothing has been attempted yet — so this is a configuration "
            "mistake an operator fixes by supplying the missing piece"
        )
    return backend.resolve(reference)


def resolve_sidecar_key(
    env: Optional[Mapping[str, str]] = None,
    *,
    backends: Optional[Mapping[str, KeyBackend]] = None,
    account: Optional[str] = None,
    journal: Optional[KeyAlertJournal] = None,
) -> EnsureKeyResult:
    """Feature 111's entry point: resolve the sidecar key, alerting on failure.

    The whole sentence — *System resolves the sidecar decryption key from KMS or
    sops, which emits an unrecoverable_state alert when decryption fails* — in
    one call.  It reads ``NULL_SIDECAR_KEY_REF``, resolves the reference through
    its backend, and hands the material to
    :func:`~nulloracle.keyref.ensure_key`, which performs the one-service-account
    check and wraps the bytes in a :class:`~nulloracle.keyref.SidecarKey`.

    **This is the call a process makes at its own startup.**  It is deliberately
    *not* what the component builders call: the factory builds every registered
    component on every :func:`~app.module_loader.create_app`, so a builder that
    emitted here would take composition down for every unrelated member — and an
    alert raised during composition is an alert nobody asked for.  A deployment
    whose scorer must hold the key calls this where failing loudly is right.

    Raises :class:`~nulloracle.keyalert.UnrecoverableStateError` (carrying the
    record, chained from the backend's failure) when a backend could not obtain
    the key, and :class:`~nulloracle.errors.SidecarKeyError` or
    :class:`~nulloracle.errors.SidecarAccessError` for a malformed reference, a
    malformed secret, or a foreign account — none of which emit an alert,
    because none of them is the unrecoverable state.

    ``created`` is always ``False``: this member resolves an *existing* key and
    has no path that mints one.  Minting is the deployment's, and feature 155's
    backup obligation hangs on the flag, so claiming to have created a key would
    be telling a caller to back up something this member never made.
    """
    source = os.environ if env is None else env
    reference = KeyReference.from_env(source)
    material = resolve_material(
        reference, backends=backends, env=source, journal=journal
    )
    return ensure_key(material, env=source, account=account)
