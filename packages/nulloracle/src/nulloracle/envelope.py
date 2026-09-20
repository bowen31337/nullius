"""The AES-GCM envelope: the sidecar file's bytes, sealed and opened.

app_spec.xml, "Null Oracle & Planted Nulls", feature 109: *System persists
null assignments in an AES-GCM encrypted sidecar file readable by exactly
one service account.*  docs/nullius-tech-architecture.md §7.1 states the
primitive and the container in one line — ``sidecar.enc  # AES-GCM, key in
KMS/sops`` — and §1 states what rests on it: the null labels are the one
secret whose leak *"silently voids every calibration number the system has
ever produced, and you would not notice."*

This module is the cipher half: :func:`seal` turns plaintext into the bytes
of a sidecar file, :func:`open_envelope` turns them back, and neither knows
what a null assignment is.  :mod:`nulloracle.assignment` owns the schema and
:mod:`nulloracle.sidecar` owns the file; keeping the cipher to bytes means
the wire format below can be reasoned about — and tested for tampering —
without a schema in the way.

**The container is pinned here, because AES-GCM alone does not pin one.**
A caller handed "AES-GCM ciphertext" has been told almost nothing: the
nonce has to come from somewhere, and if it comes from the same place
twice under the same key the whole construction fails catastrophically —
a nonce reuse in GCM leaks the XOR of two plaintexts and, worse, the
authentication key.  So the file format is stated rather than implied::

    magic           16 bytes   b"NULLIUS-SIDECAR\\x00"  (see :data:`MAGIC`)
    format version   1 byte    :data:`FORMAT_VERSION`
    nonce           12 bytes   fresh, from :func:`os.urandom`, per seal
    ciphertext      n bytes    the sealed payload
    tag             16 bytes   GCM's authentication tag, appended

The nonce is written *into the file*, not derived and not configured: a
derivation scheme is one more thing to get wrong, and §7.1's sidecar is a
single file written a handful of times, not a high-volume stream where the
random-nonce birthday bound in §8.3 of NIST SP 800-38D would ever be
approached.  Fresh random per seal, stored, and never reused because the
next seal draws another.

**The header is authenticated as associated data.**  The magic, the format
version and the nonce are passed to GCM as AAD, so they are covered by the
tag without being encrypted — exactly the property AAD is for.  Without it,
an attacker who cannot forge a sidecar could still *downgrade* one: strip
the header of a format-2 file, present it as format 1, and a reader racing
to support two versions would decrypt it under the wrong rules.  With it,
a version byte that is not the one sealed is a tag failure.

**A tag failure is one refusal, and it is loud.**  :func:`open_envelope`
raises :class:`~nulloracle.errors.SidecarDecryptionError` for every way the
open can fail — a wrong key, a flipped bit, a truncated file, a forged
header, a nonce from a different seal.  They are deliberately not
distinguished for the caller (see that error's docstring: distinguishing
them would be an oracle of its own), and the failure is deliberately never
degraded into "no assignments": §7's failure table calls sidecar key loss
*"Unrecoverable. All FDR history becomes uninterpretable"*, and the one
thing that must never happen is that an unopenable sidecar reads as a world
with no nulls in it.

**The AES-GCM implementation is ``cryptography``'s, imported on first use.**
The import lives behind :func:`require_cryptography` for the same reason
``feature_store.parquet.require_arrow`` and ``cost_model.config.require_yaml``
exist: the factory's workspace scan imports this package to fire its
``@register`` decorators, and the scan must not require a C-extension wheel
to be installed.  A hand-rolled GCM would be the alternative, and it is not
an alternative — §7.1's entire argument is that the labels are
cryptographically sealed, so this member owns a real, audited AEAD rather
than an invention of its own.
"""

from __future__ import annotations

import hashlib
import os

from .errors import SidecarDecryptionError, SidecarKeyError
from .keyref import SIDECAR_KEY_BYTES, SidecarKey

__all__ = [
    "FORMAT_VERSION",
    "MAGIC",
    "NONCE_BYTES",
    "TAG_BYTES",
    "envelope_digest",
    "open_envelope",
    "require_cryptography",
    "seal",
    "validated_key",
]

#: The file's first bytes: a fixed marker so a reader can tell a sidecar from
#: anything else that happens to be in the directory, before it spends a
#: decryption attempt discovering the same thing.
#:
#: NUL-terminated so the marker cannot be a prefix of a longer plausible
#: magic, and not itself secret — it is *meant* to be recognizable, which is
#: why it is authenticated (as part of the AAD) rather than hidden.
MAGIC = b"NULLIUS-SIDECAR\x00"

#: The container format's version.  Bumped only by a change to the layout
#: below; authenticated, so a file cannot be silently re-read as a different
#: version than the one it was sealed as.
FORMAT_VERSION = 1

#: GCM's nonce length.  96 bits is the size SP 800-38D specifies for GCM and
#: the one that needs no extra derivation step (any other length is hashed
#: into the IV first, which is a thing to get wrong for no gain).
NONCE_BYTES = 12

#: GCM's tag length: 128 bits, the full tag.  Shortened tags are permitted
#: by the standard and are a deliberate weakening; nothing here needs the
#: few bytes they would save.  Named because the format's byte layout below
#: depends on it.
TAG_BYTES = 16

#: Bytes of the file before the ciphertext body begins.
_HEADER_BYTES = len(MAGIC) + 1 + NONCE_BYTES

#: The associated data every seal and open passes to GCM: the header that
#: precedes the nonce plus the version byte — i.e. everything in the file
#: except the nonce itself, which GCM already covers as its IV.
_AAD = MAGIC + bytes([FORMAT_VERSION])


def require_cryptography():
    """Import and return the ``cryptography`` module, or raise a named error.

    The one place in this package that reaches for the AES-GCM
    implementation (see the module docstring for why the import is
    deferred).  Imported lazily on every call rather than cached in a module
    global: the cost after the first import is a ``sys.modules`` lookup, and
    a cache would be a lie in the one environment where it matters — a test
    that installs, removes or monkeypatches the module mid-process.

    A missing ``cryptography`` raises :class:`ModuleNotFoundError` naming
    the fix, following the shape of ``feature_store.parquet.require_arrow``
    and ``cost_model.config.require_yaml`` — the seam lives in the member
    that declares the dependency.  A missing *cipher* is an environment
    problem, not a corrupt sidecar, so it is deliberately not a
    :class:`~nulloracle.errors.SidecarDecryptionError`.
    """
    try:
        import cryptography
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM  # noqa: F401
    except ModuleNotFoundError as exc:  # pragma: no cover - dependency is declared
        raise ModuleNotFoundError(
            "the null sidecar is sealed with AES-GCM "
            "(docs/nullius-tech-architecture.md §7.1), which needs the "
            "cryptography package; install it (`uv sync` installs the "
            "dependency this member declares as cryptography)"
        ) from exc
    return cryptography


def _aesgcm(key: SidecarKey):
    """Build an ``AESGCM`` cipher over a validated :class:`SidecarKey`.

    The single bridge between this member's key wrapper and the library's
    cipher, so ``reveal()`` is called in exactly one place — the whole
    reason the wrapper names that method explicitly is that each call site
    is a place the secret is loose in a local, and one is a number worth
    keeping.
    """
    require_cryptography()
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    return AESGCM(key.reveal())


def validated_key(key: SidecarKey) -> SidecarKey:
    """Accept a :class:`SidecarKey` or 32 raw bytes, and nothing else.

    Bytes are accepted so the envelope can be exercised by a caller that
    already holds material from a backend, but they are wrapped rather than
    used directly — the length check happens once, in
    :class:`~nulloracle.keyref.SidecarKey`, so a short key is refused as a
    key-length mistake rather than surfacing later as a library error about
    the algorithm.

    Public because it is the single seam where "what is a key?" is decided:
    :class:`~nulloracle.sidecar.NullSidecar` validates through this rather
    than wrapping length-checked bytes itself, so the file layer and the
    cipher layer cannot disagree about what they will accept.  A second
    spelling of the rule is how one of them ends up accepting a string.

    A key from a *different module object* is accepted structurally rather
    than by ``isinstance``: the factory's scan imports this member under a
    synthetic alias, so a process can hold two ``SidecarKey`` classes, and an
    ``isinstance`` here would refuse a key the scanned sidecar component
    itself minted.  The seam that decides what a key is must not depend on
    which copy of the class the caller happened to import.
    """
    material = key.reveal() if isinstance(key, SidecarKey) else (
        _revealed(key) if callable(getattr(key, "reveal", None)) else key
    )
    if not isinstance(material, (bytes, bytearray)):
        raise SidecarKeyError(
            f"the sidecar key must be a SidecarKey or "
            f"{SIDECAR_KEY_BYTES} raw bytes, got "
            f"{type(key).__name__} (revealing "
            f"{type(material).__name__})"
        )
    if len(material) != SIDECAR_KEY_BYTES:
        raise SidecarKeyError(
            f"the sidecar key is {len(material)} bytes; AES-256-GCM takes "
            f"exactly {SIDECAR_KEY_BYTES}"
        )
    return SidecarKey(bytes(material))


def _revealed(key: object) -> object:
    """``key.reveal()``, with a non-bytes answer treated as not-a-key.

    A cross-module copy of :class:`~nulloracle.keyref.SidecarKey` is accepted
    structurally, but only that far: whatever ``reveal`` hands back must
    still be key material of the one length this member accepts.  An
    unrelated object that happens to expose a ``reveal`` attribute therefore
    fails the length or type check below and is refused with a named error,
    rather than being passed to the cipher.
    """
    try:
        return key.reveal()
    except Exception as exc:  # noqa: BLE001 - any failure is "not a key"
        raise SidecarKeyError(
            f"the sidecar key's reveal() raised "
            f"{type(exc).__name__}: {exc}; an object is a sidecar key only if "
            "it can produce the key material"
        ) from exc


def seal(plaintext: bytes, key: SidecarKey | bytes) -> bytes:
    """Seal ``plaintext`` into the bytes of a sidecar file.

    Draws a fresh nonce from :func:`os.urandom`, writes the container
    described in the module docstring, and returns the whole file.  A
    fresh nonce per call is the one invariant that makes GCM safe here, so
    it is drawn here rather than accepted as an argument: a caller who
    could supply a nonce is a caller who could supply the same one twice,
    and the failure mode of that is silence followed by total compromise.

    The plaintext is not a parameter with a default and is not optional: an
    empty sidecar is a legitimate world (a campaign with no nulls assigned),
    but it is one a caller should have to say out loud, because "I forgot to
    pass the assignments" and "this campaign has none" seal to the same
    bytes and mean very different things to the FDR that follows.
    """
    if not isinstance(plaintext, (bytes, bytearray)):
        raise SidecarKeyError(
            f"the sidecar's plaintext must be bytes, got "
            f"{type(plaintext).__name__}; the envelope seals bytes and knows "
            "nothing about the schema inside them (nulloracle.assignment "
            "owns that half)"
        )
    validated = validated_key(key)
    nonce = os.urandom(NONCE_BYTES)
    body = _aesgcm(validated).encrypt(nonce, bytes(plaintext), _AAD)
    return MAGIC + bytes([FORMAT_VERSION]) + nonce + body


def open_envelope(sealed: bytes, key: SidecarKey | bytes) -> bytes:
    """Open a sealed sidecar file, returning its plaintext.

    The inverse of :func:`seal`, and the point at which the container's
    claims are checked: the magic must match, the version byte must be the
    one this build writes, the nonce must be present, and then GCM must
    authenticate the whole thing.  Every one of those failures raises
    :class:`~nulloracle.errors.SidecarDecryptionError` with the *stage*
    named — an operator reading a traceback should be able to tell "this is
    not a sidecar file" from "this is a sidecar and it did not survive" from
    "this is a sidecar and the key is wrong", without the error ever being
    precise enough to serve as a decryption oracle to a caller who is
    guessing keys.

    A sealed file that opens to anything other than the exact bytes sealed
    is not a possibility GCM leaves open — that is what the tag is — so this
    function has no "partially valid" return path.  Either the plaintext is
    the one that was sealed under this key, or it raises.
    """
    validated = validated_key(key)
    if not isinstance(sealed, (bytes, bytearray)):
        raise SidecarDecryptionError(
            f"the sidecar's contents must be bytes, got "
            f"{type(sealed).__name__}"
        )
    data = bytes(sealed)
    if len(data) < _HEADER_BYTES + TAG_BYTES:
        raise SidecarDecryptionError(
            f"the sidecar is {len(data)} bytes, shorter than the "
            f"{_HEADER_BYTES + TAG_BYTES}-byte minimum a sealed file has; a "
            "truncated sidecar is not an empty one, and reading it as 'no "
            "nulls assigned' would report an FDR computed over nothing"
        )
    if not data.startswith(MAGIC):
        raise SidecarDecryptionError(
            "the sidecar does not begin with this member's file marker; the "
            "file at this path is not a sealed null sidecar (§7.1), so it is "
            "refused rather than opened with a schema it may not have"
        )
    version = data[len(MAGIC)]
    if version != FORMAT_VERSION:
        raise SidecarDecryptionError(
            f"the sidecar declares container format {version} and this build "
            f"writes {FORMAT_VERSION}; a newer sidecar is read by the build "
            "that wrote it, not guessed at by this one"
        )
    nonce = data[len(MAGIC) + 1 : _HEADER_BYTES]
    body = data[_HEADER_BYTES:]
    try:
        from cryptography.exceptions import InvalidTag

        return _aesgcm(validated).decrypt(nonce, body, _AAD)
    except InvalidTag as exc:
        raise SidecarDecryptionError(
            "the sidecar failed AES-GCM authentication: the key is not the "
            "one it was sealed under, or the file was altered after it was "
            "written. docs/nullius-tech-architecture.md §7 calls this the "
            "unrecoverable failure — all recorded calibration becomes "
            "uninterpretable — so it is raised rather than degraded to an "
            "empty assignment map"
        ) from exc


def envelope_digest(sealed: bytes) -> str:
    """A sha256 over the sealed file's bytes, as 64 lowercase hex characters.

    The digest of the *ciphertext*, so a process that may not hold the key
    can still tell whether two sidecar files are the same one — the read
    path a backup check, a deployment audit or a test takes.  Like
    :func:`nulloracle.assignment.assignments_digest` (which digests the
    plaintext instead), this detects a *different* file and cannot detect a
    *forged* one; only the tag does that, and only the key verifies the tag.

    Deliberately hashes the bytes as given rather than parsing them: its
    subject is the file, and a digest that refused a malformed input would
    be unable to answer the one question it is asked about a file that is
    already suspected to be wrong.
    """
    if not isinstance(sealed, (bytes, bytearray)):
        raise SidecarDecryptionError(
            f"the sidecar's contents must be bytes, got "
            f"{type(sealed).__name__}"
        )
    return hashlib.sha256(bytes(sealed)).hexdigest()
