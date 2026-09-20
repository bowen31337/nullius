"""The sidecar key reference: where the AES-GCM key comes from, and who may ask.

app_spec.xml, "Null Oracle & Planted Nulls", feature 110 is not this
module's subject, but feature 111 is: *System resolves the sidecar
decryption key from KMS or sops, which emits an unrecoverable_state alert
when decryption fails.*  docs/nullius-tech-architecture.md §7.1 states the
storage rule — *"AES-GCM, key in KMS/sops; readable by ONE service
account"* — §18 requires it — *"Null sidecar key in KMS or ``sops``,
granted to exactly one service account, with access audit-logged"* — and
§2's trust table gives the key its own row: *"null oracle + sidecar key …
separate IAM role"*.

This module owns the *naming* half of that rule: it reads
``NULL_SIDECAR_KEY_REF`` (the variable ``app_spec.xml``'s prerequisites
list), resolves it into the form the cipher needs, and refuses anything it
cannot resolve.  It deliberately does **not** call a KMS API or shell out
to ``sops``: what those two backends do — an authenticated network call to
a cloud KMS, a decryption against an age or PGP key held by an operator —
is deployment territory owned by feature 111 proper and the security
features beside it (154's audit record, 155's two-store backup), and a
member that grew a half-version of either would be a second, disagreeing
implementation of a credential path.  What this member pins instead is the
*contract* those backends are resolved behind, so that the thing being
tested on this side is the part that can be tested honestly: the reference
grammar, and the refusal of everything that is not one.

**Three reference forms are named, and the list is closed.**  A reference
is one of:

* ``kms:<arn-or-id>`` — an AWS KMS key reference, the §18 spelling.  The
  key material never leaves the KMS; the resolved value is the *ciphertext*
  the KMS returns for the data key.
* ``sops:<path>`` — a SOPS-encrypted document, the alternative §7.1 allows
  an operator who would rather not run a KMS.  The resolved value is the
  document's plaintext.
* ``hex:<64-or-32-byte-hex>`` — a raw key, the development and single-machine
  spelling (the spec's *"SQLite acceptable single-machine"* allowance has a
  key-storage counterpart).  Named ``hex:`` explicitly rather than
  accepting a bare hex string, because a bare string is indistinguishable
  from a filesystem path, and a member that guessed would eventually load
  the wrong kind of secret.

A reference that is none of the three is refused with
:class:`~nulloracle.errors.SidecarKeyError` naming the forms that are
accepted.  The refusal is deliberately *before* any cipher is touched: an
unresolvable reference is a configuration mistake, and it should read as
one, not as "the sidecar is corrupt".

**The key itself is never logged, never repr'd, and never a plain string.**
:class:`SidecarKey` wraps the bytes, redacts itself in ``repr``, and
refuses to compare equal to anything but another :class:`SidecarKey` with
the same material — so a stack trace, a debugger dump or a failed
assertion cannot spill the one secret whose leak, in §1's words, *"silently
voids every calibration number the system has ever produced"*.  The
explicit ``reveal()`` is the one door, deliberately named so that every
call site that opens it is visible in a grep.

**The account is checked here too.**  A key reference is meaningless
without knowing *who* is resolving it — §7.1 grants the file to exactly
one service account, and a resolved key is only useful to that account.
:func:`resolve_key` therefore takes the requesting account's identity and
compares it against the account the reference is granted to, refusing a
foreign caller with :class:`~nulloracle.errors.SidecarAccessError` before
the key is assembled.  The filesystem mode bits
(:mod:`nulloracle.sidecar`) are the enforcement; this check is the same
rule stated at the API, so a caller cannot reach a key by importing past
the file.
"""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Optional

from .errors import SidecarAccessError, SidecarKeyError

__all__ = [
    "KEY_REF_ENV",
    "SERVICE_ACCOUNT_ENV",
    "SIDECAR_KEY_BYTES",
    "EnsureKeyResult",
    "KeyReference",
    "SidecarKey",
    "ensure_key",
    "resolve_key",
    "service_account",
]

#: The environment variable naming where the sidecar key comes from.
#:
#: ``app_spec.xml``'s prerequisites list spells it — *"Environment variables
#: documented in .env.example: … ``NULL_SIDECAR_KEY_REF`` …"* — and §7.1
#: fixes what it points at (*"key in KMS/sops"*).  Spelled once here so the
#: member, the seat in the app namespace and any deployment template cannot
#: drift apart on the name.
KEY_REF_ENV = "NULL_SIDECAR_KEY_REF"

#: The environment variable naming the one service account the key is granted to.
#:
#: §7.1 and §18 both state the grant as *exactly one* account.  Which account
#: is a deployment fact, not a code fact, so it is configured — but the
#: *cardinality* is a code fact and is enforced here: the variable names one
#: account, and this member has no spelling for a second.
SERVICE_ACCOUNT_ENV = "NULL_SIDECAR_SERVICE_ACCOUNT"

#: The AES-GCM key length this member insists on: 32 bytes (AES-256).
#:
#: §7.1 says "AES-GCM" and nothing about key size, so the choice is made
#: here and made *narrowly on purpose*.  AES-128 (16 bytes) is not
#: accepted, not because it is broken but because accepting two lengths
#: would mean two key-length branches on the seal path, a second shape of
#: reference to test, and a subtle question at every read about which one a
#: file was written under.  One length, named, refused otherwise — and the
#: refusal is a :class:`~nulloracle.errors.SidecarKeyError`, because a
#: 16-byte secret pasted into ``hex:`` is a key-length mistake, not a
#: corrupt sidecar.
SIDECAR_KEY_BYTES = 32

_HEX = frozenset("0123456789abcdef")
_HEX_TOKEN = re.compile(r"^[0-9a-fA-F]+$")

#: The three reference schemes this member resolves, in the order the
#: docstring names them.  A closed set: see the module docstring for why
#: "some other string" is not a fourth spelling.
_SCHEMES = ("kms", "sops", "hex")


@dataclass(frozen=True)
class KeyReference:
    """A parsed ``NULL_SIDECAR_KEY_REF``: a scheme and the thing it names.

    ``scheme`` is one of :data:`_SCHEMES` and ``target`` is whatever
    followed the colon, stripped.  Parsing is separate from resolving so a
    test — or an operator's audit — can assert *what a reference claims to
    be* without needing the KMS, the sops key or the raw bytes that
    resolving it would require.  That split mirrors the cost-model member's
    parse-then-fold seam for the same reason: the naming is checkable in
    environments where the secret is not.
    """

    scheme: str
    target: str

    def __post_init__(self) -> None:
        if self.scheme not in _SCHEMES:
            raise SidecarKeyError(
                f"the sidecar key reference names the scheme "
                f"{self.scheme!r}; §7.1's key lives in KMS or sops, so the "
                f"accepted forms are "
                + ", ".join(f"{scheme}:<target>" for scheme in _SCHEMES)
                + " (a bare path or a bare hex string is refused because it "
                "is indistinguishable from the other)"
            )
        if not self.target.strip():
            raise SidecarKeyError(
                f"the sidecar key reference {self.scheme}:… carries no "
                "target; a scheme with nothing after it names no key, and "
                "resolving it would fail later as a decryption error rather "
                "than now as the configuration mistake it is"
            )

    @classmethod
    def parse(cls, reference: str) -> "KeyReference":
        """Parse a reference string, refusing anything not a named form.

        Accepts ``kms:<arn-or-id>``, ``sops:<path>`` and ``hex:<hex>``.
        Surrounding whitespace on the whole reference and on the target is
        stripped (a YAML block scalar or a ``.env`` line commonly carries
        some), but the scheme itself must be spelled exactly: a reference
        that is missing its colon, or that carries an unknown scheme, is
        refused rather than guessed at.
        """
        if not isinstance(reference, str):
            raise SidecarKeyError(
                f"the sidecar key reference must be a string, got "
                f"{type(reference).__name__}"
            )
        text = reference.strip()
        if not text:
            raise SidecarKeyError(
                f"{KEY_REF_ENV} is empty; §7.1 puts the sidecar key in "
                "KMS or sops, so an unset reference is a deployment that has "
                "not been given a key at all — and an empty one is worse, "
                "because it looks configured"
            )
        scheme, separator, target = text.partition(":")
        if not separator:
            raise SidecarKeyError(
                f"the sidecar key reference {reference!r} carries no scheme; "
                "accepted forms are "
                + ", ".join(f"{name}:<target>" for name in _SCHEMES)
                + " — a bare path is ambiguous between a sops document and a "
                "raw key file, so it is refused rather than guessed at"
            )
        return cls(scheme=scheme.strip().lower(), target=target.strip())

    @classmethod
    def from_env(
        cls, env: Optional[Mapping[str, str]] = None
    ) -> "KeyReference":
        """Parse the reference the environment names, or refuse.

        Reads :data:`KEY_REF_ENV` (``NULL_SIDECAR_KEY_REF``), with an empty
        or whitespace-only value counting as unset — the same treatment the
        shared fixtures give ``TEST_DATABASE_URL`` and the feature-store
        member gives ``LAKE_ROOT``.  An unset variable raises
        :class:`~nulloracle.errors.SidecarKeyError` rather than returning
        ``None``: the *component* degrades to absent when unconfigured (see
        :meth:`nulloracle.sidecar.NullSidecar.resolve`), but a caller who
        explicitly asks for the reference has asked a question whose honest
        answer is "there is none", and that is an error.
        """
        source = os.environ if env is None else env
        raw = source.get(KEY_REF_ENV, "")
        if not raw.strip():
            raise SidecarKeyError(
                f"{KEY_REF_ENV} is not set; §7.1 keeps the sidecar key in KMS "
                "or sops and app_spec.xml's prerequisites list this variable "
                "as the way a deployment names it"
            )
        return cls.parse(raw)

    @property
    def scheme_label(self) -> str:
        """The reference with its target redacted — safe to log.

        A KMS ARN and a sops path are not secrets themselves, but a raw
        ``hex:`` target is the key, and one accessor that is safe to log in
        every case is worth more than a rule about which targets may be
        printed.  Every message this module raises uses this, never
        ``target``.
        """
        return f"{self.scheme}:<redacted>"


class SidecarKey:
    """The AES-GCM key material, wrapped so it cannot leak by accident.

    ``repr`` and ``str`` redact; equality compares material and nothing
    else; nothing but :meth:`reveal` returns the bytes.  The wrapper exists
    because the ordinary ways a secret leaks are not attacks — they are a
    traceback printing a local, a ``print`` left in a debug branch, a
    failing assertion that helpfully renders both sides.  §1 states the
    stakes: a leaked null label *"silently voids every calibration number
    the system has ever produced, and you would not notice."*
    """

    __slots__ = ("_material",)

    def __init__(self, material: bytes) -> None:
        if not isinstance(material, (bytes, bytearray)):
            raise SidecarKeyError(
                f"key material must be bytes, got {type(material).__name__}"
            )
        if len(material) != SIDECAR_KEY_BYTES:
            raise SidecarKeyError(
                f"the sidecar key is {len(material)} bytes; AES-256-GCM takes "
                f"exactly {SIDECAR_KEY_BYTES} (see KEY_BYTES in "
                "nulloracle.keyref for why one length is accepted rather "
                "than two)"
            )
        self._material = bytes(material)

    @classmethod
    def from_hex(cls, text: str) -> "SidecarKey":
        """Build a key from a hex string, refusing a malformed one clearly.

        The one constructor a ``hex:`` reference resolves through.  An odd
        length, a non-hex character or the wrong byte count is refused with
        the *reason* named, because "invalid key" alone sends an operator
        looking at the sidecar when the problem is the secret they pasted.
        """
        if not isinstance(text, str):
            raise SidecarKeyError(
                f"the hex sidecar key must be a string, got "
                f"{type(text).__name__}"
            )
        candidate = text.strip()
        if not _HEX_TOKEN.match(candidate):
            raise SidecarKeyError(
                "the hex sidecar key carries a character outside 0-9a-f; a "
                "key that is not hexadecimal is a mistyped secret, not a "
                "cipher problem"
            )
        if len(candidate) % 2:
            raise SidecarKeyError(
                f"the hex sidecar key is {len(candidate)} characters — an odd "
                "count, so it is not a whole number of bytes"
            )
        return cls(bytes.fromhex(candidate))

    def reveal(self) -> bytes:
        """Return the key material.

        Deliberately named rather than a ``bytes()`` or a ``.value``: every
        call site that takes the key out of its wrapper should be greppable,
        because each one is a place the secret is loose in a local.
        """
        return self._material

    def __eq__(self, other: object) -> bool:
        # Compares only against another SidecarKey.  Returning False rather
        # than NotImplemented for a plain bytes/str is the point: a
        # comparison between the wrapper and the raw secret is a leak
        # attempt dressed as an assertion, and it should read as "not equal"
        # rather than as a supported operation.
        if not isinstance(other, SidecarKey):
            return NotImplemented
        return self._material == other._material

    def __hash__(self) -> int:
        return hash(self._material)

    def __repr__(self) -> str:
        return f"SidecarKey(<{len(self._material)} bytes redacted>)"

    __str__ = __repr__


def service_account(env: Optional[Mapping[str, str]] = None) -> Optional[str]:
    """The one service account the sidecar is granted to, or ``None``.

    Reads :data:`SERVICE_ACCOUNT_ENV`.  ``None`` — the variable unset or
    blank — is a *supported* answer and means "this deployment has not named
    an account", in which case the identity assertion is skipped and the
    filesystem mode bits are the whole of the enforcement.  That is
    deliberate: a member that required a configured account name would
    refuse to compose in every environment that relies on the mode bits
    alone (the single-machine allowance), and §7.1's rule is enforced by
    those bits first.  Naming an account *adds* a check; it does not gate
    one.
    """
    source = os.environ if env is None else env
    raw = source.get(SERVICE_ACCOUNT_ENV, "").strip()
    return raw or None


def resolve_key(
    reference: KeyReference,
    *,
    account: Optional[str] = None,
    granted_account: Optional[str] = None,
) -> SidecarKey:
    """Resolve a reference into key material, refusing a foreign account.

    ``account`` is the identity resolving the reference — the process's own
    service account, or an operator's explicit assertion.  ``granted_account``
    is the single account the reference is granted to (§7.1: *exactly one*).
    When both are given and they disagree, the resolution is refused with
    :class:`~nulloracle.errors.SidecarAccessError` *before* the key is
    assembled, so a foreign caller never holds the material even briefly.

    The ``hex:`` scheme resolves inline.  The ``kms:`` and ``sops:`` schemes
    do **not**: this member deliberately does not call a KMS API or shell
    out to ``sops`` (see the module docstring), so resolving either of them
    here raises :class:`~nulloracle.errors.SidecarKeyError` naming the
    backend that must supply the material.  That is not a stub — it is the
    boundary.  Feature 111 owns the backends; this module owns the grammar
    they are resolved behind, and a process that holds the material supplies
    it through :func:`ensure_key` instead.
    """
    if (
        account is not None
        and granted_account is not None
        and account != granted_account
    ):
        raise SidecarAccessError(
            f"the sidecar key is granted to the service account "
            f"{granted_account!r} and was requested by {account!r}; §7.1 seals "
            "the sidecar readable by ONE service account and §2 gives the key "
            "its own IAM role, so a second caller is not a permission this "
            "member can grant"
        )
    if reference.scheme == "hex":
        return SidecarKey.from_hex(reference.target)
    raise SidecarKeyError(
        f"the sidecar key reference {reference.scheme_label} names the "
        f"{reference.scheme!r} backend, which this member does not speak: "
        "resolving it needs the KMS call or the sops decryption that feature "
        "111 owns, and a half-version of either here would be a second, "
        "disagreeing implementation of a credential path. Resolve it in that "
        "backend and hand the material to ensure_key()"
    )


@dataclass(frozen=True)
class EnsureKeyResult:
    """What :func:`ensure_key` answers: the key, and whether this call made it.

    ``created`` exists for feature 111's alerting: the caller that *created*
    a sidecar key is the caller that must back it up (§18's *"Back up the
    key to two independent stores"*, feature 155), because §7's failure
    table calls key loss *unrecoverable* — *"All FDR history becomes
    uninterpretable"*.  A key that already existed needs no backup; a key
    that was just minted does, and this flag is how the caller knows which
    call it is holding without a second read.
    """

    key: SidecarKey
    created: bool


def ensure_key(
    material: Optional[bytes] = None,
    *,
    env: Optional[Mapping[str, str]] = None,
    account: Optional[str] = None,
) -> EnsureKeyResult:
    """Obtain the sidecar key: resolved from the environment, or supplied.

    The seam a KMS- or sops-speaking caller (feature 111) uses.  With
    ``material`` given, that is the key — the backend resolved it and this
    function's job is only the account check and the wrapping.  Without it,
    the reference in the environment is parsed and resolved, and an inline
    ``hex:`` reference yields the key while a ``kms:``/``sops:`` one is
    refused by :func:`resolve_key`.

    The account check runs on both paths: ``account`` defaults to
    :func:`service_account`'s answer, and when a granted account is
    configured, a caller that is not it is refused before it holds
    anything.  ``created`` is ``False`` whenever the caller supplied
    material — the backend knows whether it minted a key, and this member
    has no way to ask.

    Raises :class:`~nulloracle.errors.SidecarKeyError` when nothing
    supplies material and the reference cannot resolve, and
    :class:`~nulloracle.errors.SidecarAccessError` for a foreign account.
    """
    source = os.environ if env is None else env
    granted = service_account(source)
    requester = account if account is not None else granted
    if material is not None:
        return EnsureKeyResult(
            key=_account_checked(SidecarKey(material), requester, granted),
            created=False,
        )
    reference = KeyReference.from_env(source)
    if reference.scheme == "hex":
        return EnsureKeyResult(
            key=_account_checked(
                resolve_key(reference, account=requester, granted_account=granted),
                requester,
                granted,
            ),
            created=False,
        )
    raise SidecarKeyError(
        f"the sidecar key reference {reference.scheme_label} names the "
        f"{reference.scheme!r} backend; this member does not speak it (see "
        "nulloracle.keyref) — resolve the material in that backend and pass "
        "it as ensure_key(material=…)"
    )


def _account_checked(
    key: SidecarKey, requester: Optional[str], granted: Optional[str]
) -> SidecarKey:
    """Refuse ``key`` to ``requester`` when it is not the granted account.

    Split out so the check is one function rather than three copies of the
    same comparison — :func:`resolve_key` and :func:`ensure_key` both reach
    key material, and a rule enforced on one path and not the other is the
    class of bug §7.1 cannot afford.
    """
    if requester is not None and granted is not None and requester != granted:
        raise SidecarAccessError(
            f"the sidecar key is granted to the service account {granted!r} "
            f"and was requested by {requester!r}; §7.1 seals the sidecar "
            "readable by ONE service account"
        )
    return key
