"""The sidecar file: §7.1's ``sidecar.enc``, written and read by one account.

app_spec.xml, "Null Oracle & Planted Nulls", feature 109: *System persists
null assignments in an AES-GCM encrypted sidecar file readable by exactly
one service account.*  docs/nullius-tech-architecture.md §7.1 draws the
file and states the rule::

    /z0/null/
      sidecar.enc          # AES-GCM, key in KMS/sops; readable by ONE service account

:mod:`nulloracle.assignment` owns the schema and :mod:`nulloracle.envelope`
owns the cipher.  This module owns the *file*: where it lives, how it is
written so that a reader either sees the whole old sidecar or the whole new
one, and the permission rule that the sentence "readable by exactly one
service account" actually means something.

**"Readable by ONE service account" is enforced with mode bits, not with a
check in this API.**  §1 is explicit that a prompt is not a security
boundary — *"Enforce with filesystem permissions and network policy, never
with prompt instructions"* — and §2 gives the null oracle's sidecar its own
row with *"read-only mounts; separate IAM role"*.  So the file is written
``0o600`` inside a ``0o700`` directory: owner may read and write, group and
other have nothing at all, and the operating system refuses a foreign read
before any code in this package is reached.  A correct implementation that
merely *declined* to serve a foreign caller would still leave the plaintext
labels one ``cat`` away, and the whole point of the file is that they are
not.

**The read path checks the bits anyway.**  Wide-open mode bits on a sidecar
are an emergency, not a nuisance: they mean the labels are readable by every
process on the host, and §7's failure table's spirit — a leak *"silently
voids every calibration number the system has ever produced, and you would
not notice"* — is exactly this failure's shape.  So :meth:`NullSidecar.open`
refuses a sidecar whose group or other bits are set, with
:class:`~nulloracle.errors.SidecarAccessError`, rather than decrypting it
and letting the caller proceed.  The refusal is the *signal*; the mode bits
were the enforcement.

**When a deployment names its service account, the owner is checked too.**
:data:`~nulloracle.keyref.SERVICE_ACCOUNT_ENV` may name the one account the
sidecar belongs to; when it does, the file's owning uid is resolved to a
login name and compared, and a mismatch is refused.  That catches the case
mode bits alone cannot: a file copied to a foreign account *with* 0600
reproduces the bits and loses the ownership.

**Writes are atomic.**  The new sidecar is sealed to a temporary file in the
same directory (so ``os.replace`` is a rename within one filesystem, which
is atomic), chmodded ``0o600`` *before* any bytes are written to it, and
then swapped in.  The order matters: a reader racing the write either opens
the old file whole or the new file whole, and there is no instant at which
``sidecar.enc`` exists with the wrong permission bits or half its bytes.  A
crash mid-write leaves a stray ``.tmp``, never a corrupt sidecar.

**An unconfigured sidecar composes nothing.**  :meth:`NullSidecar.resolve`
returns ``None`` when neither the location nor the key is available — the
same degrade-don't-break stance the ledger member's store takes toward an
absent ``DATABASE_URL`` and the cost-model member's service takes toward an
absent document.  The composed application simply carries no sidecar
component, and a deployment whose scoring process must run §7.4's
detectability guard is, as ever, the caller that must not find itself in
that state.  That method never raises: composition builds every member's
component on every ``create_app()``, so a builder that raised would take the
whole workspace down over one member's unset environment variable.
"""

from __future__ import annotations

import os
import pwd
import stat
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any, Optional

from .assignment import (
    NullAssignment,
    decode_assignments,
    encode_assignments,
    normalize_node_id,
)
from .envelope import validated_key, envelope_digest, open_envelope, seal
from .errors import SidecarAccessError, SidecarKeyError, SidecarStoreError
from .keyref import SidecarKey, ensure_key, service_account

__all__ = [
    "SIDECAR_FILE_MODE",
    "SIDECAR_FILENAME",
    "SIDECAR_DIRECTORY",
    "SIDECAR_PATH_ENV",
    "NullSidecar",
]

#: The environment variable naming the sidecar file outright.
#:
#: ``app_spec.xml``'s prerequisites list documents ``NULL_SIDECAR_KEY_REF``
#: but not a path variable, so the variable is named here by analogy with the
#: rest of the workspace: every store this system has (the universe's tables,
#: the snapshot manifest, the cost model's document) resolves its location
#: from an environment variable with a documented default, and a sidecar that
#: could only be located by a hard-coded path would be the one store an
#: operator could not relocate.
SIDECAR_PATH_ENV = "NULL_SIDECAR_PATH"

#: §7.1's filename, verbatim.
SIDECAR_FILENAME = "sidecar.enc"

#: The directory §7.1 puts it in, under the lake root: ``/z0/null/``.
#:
#: §7.1 spells the path as ``/z0/null/``; §4.2 makes the lake the mounted,
#: hash-checked store this workspace reads, and §2 gives the null oracle a
#: read-only mount of its own.  So the sidecar's default location is the
#: lake's ``null/`` directory — the deployment's mount point *is* the
#: ``/z0`` the architecture draws, which is why the default is stated
#: relative to ``LAKE_ROOT`` rather than as the absolute path §7.1 uses for
#: illustration.
SIDECAR_DIRECTORY = "null"

#: Owner read-only in effect, owner read/write in fact — and nothing for
#: group or other.
#:
#: ``0o600`` rather than ``0o400``: the file must be *rewritable* by the one
#: account that owns it (a campaign writes its assignments, §7.4's guard and
#: a later campaign both follow), and the read-only mount §2 describes is
#: the deployment's to provide at the mount layer.  Baked-in immutability
#: here would make the sidecar unwritable in the single-machine
#: configuration the spec explicitly allows, without making it any less
#: readable by the account that holds the key.
SIDECAR_FILE_MODE = 0o600

#: The directory's mode: owner may enter and list, nobody else may do either.
#:
#: A ``0o600`` file inside a world-executable directory is still enumerable —
#: the *names* leak, and a name here is a ``node_id`` with a campaign's
#: universe size attached.  ``0o700`` closes that.
SIDECAR_DIRECTORY_MODE = 0o700

#: Bits that must not be set on the sidecar's file or its directory.
_FORBIDDEN_BITS = stat.S_IRWXG | stat.S_IRWXO


def _owner_name(uid: int) -> Optional[str]:
    """The login name for ``uid``, or ``None`` when it cannot be resolved.

    Used by the ownership check, and deliberately tolerant: a uid with no
    passwd entry (a container running under a bare numeric uid) returns
    ``None`` and the caller then relies on the mode bits alone, rather than
    refusing every read in an environment where names simply are not
    configured.  Falling back to *less* checking is the right direction
    here only because the mode bits — the actual enforcement — are still
    checked first and unconditionally.
    """
    try:
        return pwd.getpwuid(uid).pw_name
    except (KeyError, OSError):  # pragma: no cover - depends on the host
        return None


class NullSidecar:
    """§7.1's ``sidecar.enc``: the null assignments, sealed, at one path.

    Constructed with the path it owns, the key it seals under, and — when
    the deployment names one — the single service account it belongs to.
    :meth:`write` persists a whole assignment map, :meth:`open` reads the
    whole map back, and :meth:`assignment` answers for one node.

    The class holds no cache: every read opens the file.  A memo here would
    be a second copy of the labels living in process memory, which is a
    materially worse thing to have than a second disk read — the file is
    sealed and mode-``0600`` precisely so that reading it is the controlled
    operation, and a cache would move the controlled operation to
    construction and then leak the plaintext for the process's lifetime.
    """

    def __init__(
        self,
        path: "str | os.PathLike[str]",
        key: SidecarKey | bytes,
        *,
        account: Optional[str] = None,
    ) -> None:
        if isinstance(path, str) and not path.strip():
            raise SidecarStoreError(
                "the sidecar path is empty; an empty path is not a default, "
                "it is a deployment that meant to configure one and did not"
            )
        self._path = Path(path).expanduser()
        # Validated through the envelope's own seam rather than by wrapping
        # here: that is where "a SidecarKey or 32 raw bytes" is decided, and
        # a second spelling of the rule would let the sidecar and the cipher
        # disagree about what a key is.  A string, a short key and a
        # mis-sized bytes object all surface as a named SidecarKeyError.
        self._key = validated_key(key)
        self._account = account

    # -- Construction -------------------------------------------------------

    @classmethod
    def resolve(
        cls,
        env: Optional[Mapping[str, str]] = None,
        *,
        material: Optional[bytes] = None,
    ) -> Optional["NullSidecar"]:
        """The sidecar this environment names, or ``None`` when unconfigured.

        Resolution order for the path: ``NULL_SIDECAR_PATH`` when set (empty
        or whitespace-only counts as unset), else
        ``<LAKE_ROOT>/null/sidecar.enc``, else ``<workspace root>/lake/null/
        sidecar.enc``.  With none of the three available this returns
        ``None`` rather than raising or guessing — an unconfigured sidecar is
        a discoverable state, and composing an application must never fail
        because one member had no configuration.

        The *key* is resolved through :func:`~nulloracle.keyref.ensure_key`,
        so the same three reference forms apply and the account check runs
        before any material is returned.

        **This method never raises.**  A key this environment cannot supply —
        no reference at all, or a reference naming a backend this member does
        not speak — resolves to ``None``, the same "no sidecar here" answer
        as an absent path.  The reason is not a preference but the factory's
        own contract: :func:`~app.module_loader.create_app` builds *every*
        registered component on *every* call, so a builder that raised would
        take composition down for every unrelated feature in the workspace,
        and one member's unconfigured environment is not a fault the other
        members should pay for.  The ledger member's store takes exactly this
        stance toward an absent ``DATABASE_URL``.

        The consequence is deliberate and worth stating plainly: a
        deployment that *did* configure a path and a ``kms:`` reference
        composes no sidecar rather than failing loudly, so a process that
        requires one must ask a direct question — :func:`~nulloracle.keyref.
        ensure_key` raises the named
        :class:`~nulloracle.errors.SidecarKeyError` — at its own startup,
        where failing loudly is the right behaviour.  The distinction is the
        one the whole error taxonomy rests on: *no sidecar is configured*
        and *the sidecar is broken* are different facts, and only the second
        may ever be quiet.

        ``material`` short-circuits the key resolution for a process that
        already holds the key from its backend — the same seam
        :func:`~nulloracle.keyref.ensure_key` offers, threaded through here
        because a KMS-speaking caller composes the sidecar, not the key.
        """
        source = os.environ if env is None else env
        path = cls._resolve_path(source)
        if path is None:
            return None
        try:
            key = (
                ensure_key(material, env=source).key
                if material is not None
                else ensure_key(env=source).key
            )
        except SidecarKeyError:
            # See the docstring: an unconfigured or unresolvable key is a
            # discoverable state this builder degrades on, never a reason to
            # fail the composition of every other member.
            return None
        return cls(path, key, account=service_account(source))

    @staticmethod
    def _resolve_path(env: Mapping[str, str]) -> Optional[Path]:
        """Where the sidecar lives, or ``None`` when nothing names a place.

        Split out from :meth:`resolve` so the path question can be asked —
        and tested — without a key in hand.  That matters more than it looks:
        the *location* of the sidecar is not a secret (the file is sealed),
        so an audit, a backup check or an operator's inventory should be able
        to locate it in an environment that deliberately cannot decrypt it.
        """
        raw = env.get(SIDECAR_PATH_ENV, "").strip()
        if raw:
            return Path(raw).expanduser()
        lake = env.get("LAKE_ROOT", "").strip()
        if lake:
            return Path(lake).expanduser() / SIDECAR_DIRECTORY / SIDECAR_FILENAME
        # The workspace root is located through the factory's own discovery
        # rather than a hard-coded guess, exactly as the feature-store
        # member's materialiser does — a default that could silently point
        # somewhere the declaration does not cover is worse than no default.
        from app.module_loader import find_workspace_root

        root = find_workspace_root()
        if root is not None:
            return root / "lake" / SIDECAR_DIRECTORY / SIDECAR_FILENAME
        return None

    # -- Paths --------------------------------------------------------------

    @property
    def path(self) -> Path:
        """The sidecar file's path.

        Safe to expose and safe to log: the path is not a secret, and a
        member that hid it would make every deployment question about *where
        the sidecar went* unanswerable.
        """
        return self._path

    @property
    def directory(self) -> Path:
        """The directory the sidecar lives in, created on first write."""
        return self._path.parent

    @property
    def account(self) -> Optional[str]:
        """The single service account the sidecar belongs to, or ``None``."""
        return self._account

    def exists(self) -> bool:
        """Whether a sidecar file is present at this path.

        Deliberately not a "is a sidecar configured" question — that is
        whether :meth:`resolve` returned anything.  This is the filesystem
        read, and it is honest about the distinction: a configured sidecar
        that has never been written does not exist yet, and a campaign
        reading one it never wrote is a real bug worth being able to see.
        """
        return self._path.is_file()

    # -- Feature 109: writing -----------------------------------------------

    def write(
        self,
        assignments: Mapping[Any, NullAssignment] | Iterable[NullAssignment],
    ) -> str:
        """Seal ``assignments`` and persist them as the sidecar file.

        Returns the sha256 of the sealed bytes — the value an audit, a
        backup check or a test compares across two sidecars without holding
        the key (:func:`nulloracle.envelope.envelope_digest`).

        The write is whole-file and atomic: an empty assignment map is a
        legitimate sidecar (a campaign that assigned no nulls) and is
        written as one, rather than by deleting the file — a *missing*
        sidecar and an *empty* one are different facts about a campaign, and
        a reader must be able to tell them apart.  Section §7.4's guard runs
        against whatever this wrote, so "we planted nothing" has to survive
        as a statement rather than as an absence.
        """
        sealed = seal(encode_assignments(assignments), self._key)
        directory = self.directory
        try:
            directory.mkdir(parents=True, exist_ok=True)
            # The directory is tightened before the file lands in it, so
            # there is no instant at which the sidecar's name is listed by
            # a process that should not know it exists.
            os.chmod(directory, SIDECAR_DIRECTORY_MODE)
        except OSError as exc:
            raise SidecarStoreError(
                f"the sidecar directory {directory} could not be prepared: "
                f"{exc}"
            ) from exc
        temporary = directory / f".{SIDECAR_FILENAME}.{os.getpid()}.tmp"
        try:
            # ``os.open`` with the mode, rather than ``write_bytes`` followed
            # by a chmod: the file must never exist with wider bits than
            # this, not even for the instant between two syscalls, because
            # that instant is one an attacker can win by polling.
            descriptor = os.open(
                temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, SIDECAR_FILE_MODE
            )
            try:
                os.write(descriptor, sealed)
            finally:
                os.close(descriptor)
            os.replace(temporary, self._path)
        except OSError as exc:
            # Best-effort cleanup; the original failure is the one worth
            # reporting, so a failed unlink here must not mask it.
            try:
                temporary.unlink()
            except OSError:  # pragma: no cover - cleanup only
                pass
            raise SidecarStoreError(
                f"the sidecar at {self._path} could not be written: {exc}"
            ) from exc
        return envelope_digest(sealed)

    # -- Feature 109: reading -----------------------------------------------

    def open(self) -> dict[str, NullAssignment]:
        """Open the sidecar, returning §7.1's assignment map.

        Refuses, in this order — and the order is the point, because each
        refusal means something different to the operator reading it:

        1. a missing file (:class:`~nulloracle.errors.SidecarStoreError`) —
           no sidecar has been written here;
        2. a foreign reader (:class:`~nulloracle.errors.SidecarAccessError`)
           — the mode bits are wide, or the file belongs to another account;
        3. an unauthenticated file
           (:class:`~nulloracle.errors.SidecarDecryptionError`) — the key is
           wrong or the file was altered;
        4. an authenticated file that is not §7.1's schema
           (:class:`~nulloracle.errors.SidecarError`).

        Nothing here ever returns an empty map as a way of reporting a
        failure.  That is the one behaviour §7 cannot survive: "no node is
        null" is a statement about the world, and a system that answered it
        whenever the key was missing would go on to report an FDR over a
        world whose nulls had silently become real.
        """
        if not self._path.is_file():
            raise SidecarStoreError(
                f"no sidecar exists at {self._path}; §7.1's file is written by "
                "the campaign that assigns nulls, so its absence means the "
                "assignments were never persisted — not that none were made"
            )
        self._assert_readable()
        return decode_assignments(open_envelope(self._path.read_bytes(), self._key))

    def assignment(self, node_id: Any) -> Optional[NullAssignment]:
        """One node's assignment, or ``None`` when the sidecar does not hold it.

        The read the oracle's own resolution path takes (§7.2's *"if
        ``is_null``, return ``block_permute(forward_returns, seed=perm_seed,
        block=20d)``; else return the real forward returns"*).  ``None`` here
        means *this node is not in the sidecar* — which, for a campaign that
        assigned its nulls, is the honest answer for a real node's whole
        subtree.  It does **not** mean the sidecar failed to open: that
        raises, as :meth:`open` does, so a caller can never mistake a broken
        sidecar for a real world.

        Still a whole-file read per call, and deliberately not memoized —
        see the class docstring on why the labels do not live in a cache.
        """
        return self.open().get(normalize_node_id(node_id))

    # -- The one-account rule ------------------------------------------------

    def _assert_readable(self) -> None:
        """Refuse to open a sidecar whose permissions admit a second account.

        Two checks, in order of what they can prove.  The mode bits are the
        enforcement §7.1 describes — group and other must have nothing at
        all — and they are checked first, on the file and on its directory,
        because wide bits are the failure that actually happens (a copy, a
        chmod -R, an archive extraction that did not preserve modes).  The
        ownership check runs second and only when the deployment named an
        account: it catches the file that kept its bits and lost its owner.
        """
        for target, kind in ((self._path, "sidecar"), (self.directory, "directory")):
            try:
                mode = stat.S_IMODE(os.stat(target).st_mode)
            except OSError as exc:  # pragma: no cover - race with a deletion
                raise SidecarStoreError(
                    f"the sidecar {kind} {target} could not be examined: {exc}"
                ) from exc
            if mode & _FORBIDDEN_BITS:
                raise SidecarAccessError(
                    f"the sidecar {kind} {target} has mode "
                    f"{stat.filemode(os.stat(target).st_mode)}; §7.1 seals the "
                    "sidecar readable by ONE service account, so group or "
                    "other permission on it is a leak of the null labels — "
                    "the one failure that silently voids every calibration "
                    "number the system has produced. Restore "
                    f"{oct(SIDECAR_FILE_MODE if kind == 'sidecar' else SIDECAR_DIRECTORY_MODE)} "
                    f"permissions on the {kind} before reading"
                )
        if self._account is None:
            return
        try:
            owner = _owner_name(os.stat(self._path).st_uid)
        except OSError as exc:  # pragma: no cover - race with a deletion
            raise SidecarStoreError(
                f"the sidecar {self._path} could not be examined: {exc}"
            ) from exc
        if owner is not None and owner != self._account:
            raise SidecarAccessError(
                f"the sidecar at {self._path} is owned by {owner!r} and this "
                f"deployment grants it to {self._account!r}; §7.1 grants the "
                "sidecar to exactly one service account, and a file that "
                "kept its mode bits and lost its owner is the case the bits "
                "alone cannot see"
            )
