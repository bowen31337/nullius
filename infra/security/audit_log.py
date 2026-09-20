"""Feature 154's record: one audit line per read of the null sidecar key.

app_spec.xml, "Trust Zone Isolation & Secrets", feature 154: *System
persists an access audit record per read of the null sidecar key, which
exactly one service account may request.*  docs/nullius-tech-architecture.md
§18 states the rule whole — *"Null sidecar key in KMS or ``sops``, granted to
exactly one service account, with access audit-logged"* — and §2's trust
table gives the key its own row (*"null oracle + sidecar key … separate IAM
role"*).  Three of this category's members are the other halves of that
sentence and are deliberately *not* this module's subject:

* :mod:`infra.security.key_backup` (feature 155) is the key's *durability* —
  the sealed backup in two independent stores.  It asks whether the key can
  still be recovered.
* :mod:`infra.security.host_access` (feature 156) is the *zone's* gate — an
  arrival at the live trading host, admitted only through a bastion session.
  It asks whether a network path exists.
* The null oracle member (``packages/nulloracle``) owns the key's *grammar
  and identity*: ``NULL_SIDECAR_KEY_REF``'s three reference forms, the
  ``SidecarKey`` wrapper that refuses to leak, and the account comparison
  that refuses a foreign caller (feature 111's ``keyref``).

This module owns the remaining word: **audit-logged**.  A read of the
sidecar key produces a *record*, durably, and the record is what makes the
one-account rule checkable after the fact rather than only enforceable at
the moment.

**The record is written per read, and "read" is the key's arrival — not the
file's.**  The distinction is the whole design.  Reading ``sidecar.enc``
without the key yields ciphertext and teaches nothing; the secret in
question is the *key*, and the moment it exists in a caller's hands is the
moment ``keyref.ensure_key`` returns it.  So the audited event is the
resolution: one record per key obtained.  A process that reads the file
twice through one held key performed one key read; a process that resolves
the key twice performed two, and both are recorded.  Counting the second
kind is what an auditor wants, because the second kind is the one that
grows with a leaking caller.

**The record is written whether the read succeeds or is refused.**  A
refusal is the more interesting line.  §7.1's rule is *exactly one* account,
so an attempt by a second account is the event the whole feature exists to
surface — an audit that recorded only the successful reads would be silent
about precisely the reads an operator needs to see.  So a refused attempt
gets a record too, carrying both identities: the requester that asked and
the account the key is granted to.  The record does not carry the key, the
reference target, or any material — only the decision.

**The record carries no secret, and that is enforced by construction, not by
discipline.**  :class:`AuditRecord` has no field that can hold key material:
identity, outcome, the redacted reference *label*
(``SidecarKey(…)``-style — see ``keyref.KeyReference.scheme_label``), a
correlation id and a timestamp.  Its ``__repr__`` renders no more than its
fields, and its serialised form (:meth:`AuditRecord.to_json`) is a flat
object of strings and numbers.  A field-set that cannot express the secret
is a stronger guarantee than a redaction rule, because a redaction rule is
a thing someone can forget to apply.

**The log is append-only and self-chaining.**  §2's enforcement column names
the ledger as *"append-only"*, and this log takes the same stance for the
same reason: §7's failure table's spirit is that the failures worth finding
are the ones nobody would notice.  An audit record with no predecessor link
is a record a later hand can drop without leaving a trace, so each record
carries the digest of the one before it (:meth:`AuditLog.append`), and
:meth:`AuditLog.verify` re-derives the chain and refuses a gap or an edit.
Chaining does not make the log tamper-*proof* — nothing stdlib-only is, and
the store is a deployment's — but it makes tampering *detectable*, which is
the property an audit record is for.  The genesis record chains from
:data:`GENESIS` so the first line is verifiably first.

**A sink that cannot persist refuses the read.**  The one design decision
here worth arguing for.  It is tempting to let an audit failure be a warning
— the key is needed, the log is bookkeeping — but that inverts the feature:
if the record can be skipped, then the *absence* of a record stops meaning
"nobody read the key" and starts meaning "nobody read the key, or the log
was down, or someone turned it off".  An un-auditable read of the one secret
whose leak §1 says *"silently voids every calibration number the system has
ever produced"* is a read that must not happen, so
:meth:`AuditLog.record_read` raises :class:`AuditSinkError` and the caller
loses the key.  Fail closed, on the same doctrine as feature 156's gate.

Stdlib-only, like the rest of this tree: the sink is a deployment's
(a file, a KMS audit stream, a SQL table reached by a caller's own writer),
and this module is the record's shape, the chain, and the accounting.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Final

__all__ = [
    "AUDIT_LOG_PATH_ENV",
    "GENESIS",
    "KEY_REF_ENV",
    "RECORD_VERSION",
    "SERVICE_ACCOUNT_ENV",
    "AuditChainError",
    "AuditDecision",
    "AuditLog",
    "AuditRecord",
    "AuditSink",
    "AuditSinkError",
    "AuditTrailError",
    "FileAuditSink",
    "InMemoryAuditSink",
    "KeyAuditError",
    "KeyReadAudit",
    "audited_key_read",
    "describe_reference",
]

#: The environment variable naming the audit log file outright.
#:
#: Named by analogy with the rest of this tree rather than quoted from the
#: spec — ``app_spec.xml``'s prerequisites list documents
#: ``NULL_SIDECAR_KEY_REF`` and the sidecar's own path variable
#: (``nulloracle.sidecar.SIDECAR_PATH_ENV``) and no audit variable, so the
#: variable is named here the way a sibling operator-code member names the
#: path of a store a deployment must be able to relocate.  A log whose
#: location could only be a hard-coded path would be the one audit an
#: operator could not move off a full disk.
AUDIT_LOG_PATH_ENV = "NULL_SIDECAR_AUDIT_LOG"

#: The chain's root: the digest a genesis record names as its predecessor.
#:
#: 64 zeroes — not ``""`` and not ``None`` — so the first record's
#: ``previous_digest`` is the same *shape* as every other record's, and a
#: chain walk needs no special case for the beginning.  A verifier that
#: accepted a missing predecessor for the first record would accept a
#: *dropped* first record under the same rule, which is the failure the
#: genesis value removes.
GENESIS: Final[str] = "0" * 64

#: The record format's version.  Authenticated by the chain digest like every
#: other field, and bumped only when the layout below changes, so a log
#: written by one build is verified by that build rather than re-read under
#: another's rules.
RECORD_VERSION: Final[int] = 1

#: The environment variable naming the sidecar key reference — restated here
#: rather than imported for the same reason ``key_backup`` restates the
#: key length: the null oracle member is deliberately not on this tree's
#: import graph (see ``infra/security/__init__.py``), so the name is spelled
#: out (and the refusal cites its true home) instead of reached across the
#: workspace boundary.  Mirrors ``nulloracle.keyref.KEY_REF_ENV``.
KEY_REF_ENV: Final[str] = "NULL_SIDECAR_KEY_REF"

#: The environment variable naming the one account the key is granted to.
#: Mirrors ``nulloracle.keyref.SERVICE_ACCOUNT_ENV``.
SERVICE_ACCOUNT_ENV: Final[str] = "NULL_SIDECAR_SERVICE_ACCOUNT"


class AuditTrailError(Exception):
    """Base of the access-audit taxonomy.

    One base class so a caller — the key-minting path that must audit the
    key it hands out (feature 111), an operator's audit job, a later feature
    in this category — can catch every failure of the audit path with a
    single ``except``.  The subclasses split by *which contract* was
    violated, not by which line failed, in the same discipline as
    :mod:`infra.security.key_backup`'s taxonomy.
    """


class AuditSinkError(AuditTrailError):
    """The record could not be persisted — so the read it describes is refused.

    Raised when a sink raises on append, or returns something other than the
    record it was given.  Deliberately *not* swallowed by
    :meth:`AuditLog.record_read`: an audit record that can silently go
    missing stops being evidence, because the absence of a line would then
    mean "nobody read the key" *or* "the log was down", and the whole point
    of feature 154 is that the first of those is a checkable fact.  So the
    failure is loud and the caller loses the key it was trying to read —
    fail closed, the same doctrine feature 156's gate is built on.
    """


class AuditChainError(AuditTrailError):
    """A log's chain does not verify — a record was dropped, reordered or edited.

    Raised by :meth:`AuditLog.verify` when a record's ``previous_digest`` is
    not the digest of the record before it, when the first record does not
    chain from :data:`GENESIS`, or when a record's own digest does not
    re-derive from its fields.  This is the *detection*, and it is the reason
    the log is chained at all: §7's failure table's spirit is that the
    failures worth finding are the ones nobody would notice, and a silently
    shortened audit log is exactly that shape.  A chain is not tamper-proof
    — nothing stdlib-only is — but a break is at least an answer rather than
    a silence.
    """


class KeyAuditError(AuditTrailError):
    """A key read was refused — the record of the refusal is what is returned.

    Raised by :meth:`KeyReadAudit.read` when the requesting account is not
    the one account the key is granted to (§7.1: *"readable by ONE service
    account"*).  **The refusal is recorded before it is raised**: the sink
    has the line first, so an operator reading the log sees the attempt —
    which is the more interesting line of the two, because a successful read
    by the granted account is the expected case and a refused read by a
    second account is the event the feature exists to surface.  If the
    record *cannot* be written, the refusal still stands and
    :class:`AuditSinkError` is raised in place of this one: an unrecorded
    refusal is worse than an unrecorded read.
    """


class AuditDecision:
    """The two outcomes a key read can have, as the log spells them.

    A closed set of two strings, not a bool: ``"granted"`` and ``"refused"``
    read the same in a log line, a JSON object and an operator's grep, and
    an audit vocabulary that says what happened is worth more than a flag
    whose polarity a reader has to remember.
    """

    GRANTED: Final[str] = "granted"
    REFUSED: Final[str] = "refused"

    #: Both, in the order the log writes them — so a test, a filter or a
    #: dashboard enumerates the vocabulary rather than restating it.
    ALL: Final[tuple[str, ...]] = (GRANTED, REFUSED)


def describe_reference(reference: str | None) -> str:
    """A reference string reduced to something safe to log.

    ``kms:<arn>`` becomes ``kms:<redacted>``; a bare string with no scheme
    becomes ``<redacted>``; anything that is not a string the same.  This
    restates the rule ``nulloracle.keyref.KeyReference.scheme_label``
    enforces at the source (a ``hex:`` target *is* the key, so it is never
    printable), because this module deliberately does not import that one —
    and a caller that hands a raw reference here instead of a pre-redacted
    label should not be able to leak the key through its own audit log.

    **Idempotent on its own output**, which is why :meth:`AuditLog.append`
    can take either a raw reference or an already-reduced label through one
    parameter: ``describe_reference("kms:<redacted>")`` is itself, a
    ``<redacted>`` target surviving the reduction unchanged, and
    :data:`_NO_REFERENCE` likewise.  The function is total: it never raises,
    whatever it is handed.
    """
    if reference is None:
        return _NO_REFERENCE
    if not isinstance(reference, str):
        return _REDACTED
    scheme, separator, _target = reference.strip().partition(":")
    if separator and scheme.strip():
        return f"{scheme.strip().lower()}:{_REDACTED}"
    # A bare string has no scheme to keep, and — unlike ``<redacted>`` and
    # ``<none>`` themselves — cannot be recognized as already-reduced, so it
    # reduces to the scheme-less marker rather than to itself.
    if reference.strip() in (_REDACTED, _NO_REFERENCE):
        return reference.strip()
    return _REDACTED


#: The marker a reference with a scheme reduces its target to.  A named
#: constant because :func:`describe_reference` must recognize its own output
#: to stay idempotent — a bare ``"<redacted>"`` spelled twice would be two
#: values that had to agree.
_REDACTED: Final[str] = "<redacted>"

#: The marker an absent reference reduces to.
_NO_REFERENCE: Final[str] = "<none>"


class AuditRecord:
    """One line of the access audit: who read the key, and how it came out.

    The field set is the guarantee.  Every field is an identity, a decision,
    a redacted label, a counter or a timestamp — there is no field that can
    hold key material, no field that can hold the reference's *target*, and
    no free-text ``detail`` into which a caller could paste either.  That is
    deliberate and it is stronger than a redaction rule: a record that
    *cannot* express the secret cannot leak it, whereas one that merely
    promises to redact it can be made to forget.

    ``sequence`` is the record's position in its log (0-based) and
    ``previous_digest`` is the digest of the record before it —
    :data:`GENESIS` for the first.  Together they are the chain: :meth:`
    digest` hashes the canonical rendering of every field *including* the
    predecessor link, so an edited record's digest changes, a dropped
    record's successor no longer names it, and either is caught by
    :meth:`AuditLog.verify`.
    """

    __slots__ = (
        "decision",
        "granted_account",
        "previous_digest",
        "reason",
        "reference_label",
        "requester_account",
        "sequence",
        "timestamp",
        "version",
    )

    def __init__(
        self,
        *,
        sequence: int,
        previous_digest: str,
        requester_account: str | None,
        granted_account: str | None,
        decision: str,
        reference_label: str,
        reason: str,
        timestamp: float,
        version: int = RECORD_VERSION,
    ) -> None:
        if decision not in AuditDecision.ALL:
            raise AuditTrailError(
                f"an access-audit record's decision is {decision!r}; the "
                f"vocabulary is {', '.join(AuditDecision.ALL)} — a third "
                "outcome would be a read that neither happened nor was "
                "refused, and no operator could act on it (feature 154)."
            )
        if not isinstance(sequence, int) or isinstance(sequence, bool) or sequence < 0:
            raise AuditTrailError(
                f"an access-audit record's sequence is {sequence!r}; the "
                "position in the log is a non-negative integer, because the "
                "chain is walked by it and a record that cannot say where it "
                "sits cannot be shown to follow the one before it "
                "(feature 154)."
            )
        if not isinstance(previous_digest, str) or len(previous_digest) != 64:
            raise AuditTrailError(
                f"an access-audit record's previous_digest is "
                f"{previous_digest!r}; the predecessor link is a 64-character "
                f"sha256 hexdigest — {GENESIS!r} for the first record — so "
                "every record's link has the same shape and the chain needs "
                "no special case at its start (feature 154)."
            )
        self.sequence = sequence
        self.previous_digest = previous_digest
        self.requester_account = requester_account
        self.granted_account = granted_account
        self.decision = decision
        self.reference_label = reference_label
        self.reason = reason
        self.timestamp = float(timestamp)
        self.version = int(version)

    @property
    def granted(self) -> bool:
        """Whether this record describes a read that was allowed."""
        return self.decision == AuditDecision.GRANTED

    def to_json(self) -> str:
        """The record as a flat JSON object — the form a sink persists.

        Sorted keys and no whitespace, so the same record serialises to the
        same bytes on every run and in every Python: the chain digest is
        taken over this rendering, and a log that re-derived differently
        from the same fields would fail its own verification for a reason
        that had nothing to do with tampering.
        """
        return json.dumps(
            {
                "decision": self.decision,
                "granted_account": self.granted_account,
                "previous_digest": self.previous_digest,
                "reason": self.reason,
                "reference_label": self.reference_label,
                "requester_account": self.requester_account,
                "sequence": self.sequence,
                "timestamp": self.timestamp,
                "version": self.version,
            },
            sort_keys=True,
            separators=(",", ":"),
        )

    def digest(self) -> str:
        """The sha256 of this record's canonical rendering — the chain link.

        Taken over :meth:`to_json`, so it covers every field *and* the
        predecessor link.  An edited record therefore fails to re-derive its
        own digest, and a dropped record leaves its successor naming a
        digest nothing in the log produces: the two ways a log is quietly
        shortened, both caught by one value.
        """
        return hashlib.sha256(self.to_json().encode("utf-8")).hexdigest()

    def __repr__(self) -> str:
        """A record's repr names its decision and its accounts, never a secret.

        Renders only the fields, and the field set holds nothing secret — so
        unlike the key wrapper's redacting repr this one needs no special
        case.  That is the point of choosing the fields the way this class
        does.
        """
        return (
            f"AuditRecord(seq={self.sequence}, decision={self.decision!r}, "
            f"requester={self.requester_account!r}, "
            f"granted={self.granted_account!r}, "
            f"reference={self.reference_label!r})"
        )


class AuditSink:
    """One durable place the audit records go — the log's storage half.

    The abstraction the record's persistence quantifies over.  A sink
    *appends* a record and returns it; it holds no chain state of its own
    (the sequence and the predecessor link are
    :class:`AuditLog`'s to compute, so a sink cannot invent a position in
    the log), and it never sees the key.  Concrete sinks implement
    :meth:`append` and :meth:`records`; subclass this for a real backend —
    a KMS audit stream, a Postgres table, a syslog facility — and the
    record's shape and the chain stay here.

    :meth:`records` reads the sink back, which is what an operator's
    verification walks.  A sink that cannot read back what it appended is
    not a sink :class:`AuditLog` will trust: the append is confirmed by
    recall, the same way :meth:`infra.security.key_backup.BackupStore.write`
    is.
    """

    __slots__ = ("_name",)

    def __init__(self, name: str) -> None:
        if not isinstance(name, str) or not name.strip():
            raise AuditTrailError(
                f"an audit sink must have a non-empty name, got {name!r}. "
                "The name is how an operator's log line says which sink holds "
                "the record, and a sink that cannot be named cannot be "
                "reported as the one that failed (feature 154)."
            )
        self._name = name.strip()

    @property
    def name(self) -> str:
        """This sink's name — how a failure and a log line identify it."""
        return self._name

    def append(self, record: AuditRecord) -> AuditRecord:
        """Persist ``record`` durably and return it.  Abstract."""
        raise NotImplementedError(
            f"{type(self).__name__} must implement append() (feature 154)."
        )

    def records(self) -> tuple[AuditRecord, ...]:
        """Every record this sink holds, in append order.  Abstract."""
        raise NotImplementedError(
            f"{type(self).__name__} must implement records() (feature 154)."
        )


class InMemoryAuditSink(AuditSink):
    """A sink that holds the audit records in process memory.

    The test double and the ephemeral deployment: records live in an
    instance attribute, so a read audited against it can be read back in the
    same process, and nothing survives the process.  It is a sink like any
    other to :class:`AuditLog` — the chain and the per-read rule do not care
    where the lines go — which is why a suite exercises the real logic
    through it rather than around it.  Instance state, not class state: two
    in-memory sinks are two independent places, and a shared class attribute
    would make them one.
    """

    def __init__(self, name: str) -> None:
        super().__init__(name)
        self._held: list[AuditRecord] = []

    def append(self, record: AuditRecord) -> AuditRecord:
        self._held.append(record)
        return record

    def records(self) -> tuple[AuditRecord, ...]:
        return tuple(self._held)


class FileAuditSink(AuditSink):
    """A sink that appends one JSON line per record to a single ``0o600`` file.

    The single-machine and operator-script spelling: newline-delimited JSON,
    appended with ``os.O_APPEND`` so a concurrent writer's line cannot
    interleave with this one's, and created ``0o600`` *before* any byte
    lands in it — the same discipline the null sidecar is written with, for
    the same reason.  The file's contents are not secret (a record holds no
    key material), but the file *names the accounts and the read history of
    the one key the system cannot leak*, so it is owner-only anyway: what an
    attacker would learn from it is who to impersonate and when the key is
    read, which is worth more than an empty file is.

    **The directory is tightened too, and a pre-existing file is corrected.**
    ``0o600`` on the file is worth nothing if the directory is world-listable
    — the *names* leak, and the discipline is the sidecar's, which chmods its
    directory ``0o700`` for exactly that reason.  And ``os.O_CREAT``'s mode
    applies only when the file is *created*: a log that already exists with
    wider bits (a restore from an archive that dropped modes, a
    ``chmod -R``) would keep them forever, silently, while the sink reported
    success.  Both are corrected on every append rather than only at
    creation, because both are states a deployment drifts *into*.

    A line that will not parse is refused (:class:`AuditTrailError`) rather
    than skipped.  A log with one unreadable line in it is a log whose chain
    cannot be verified, and a reader that silently skipped the line would
    report the chain intact over a record it never checked — the exact shape
    of failure :meth:`AuditLog.verify` exists to refuse.

    The log is deliberately *not* opened through a symlink-resolving check:
    a deployment may legitimately point the log at a mounted volume, and
    refusing symlinks would break that while adding nothing — the directory
    and file modes above are the enforcement, and they follow the link.
    """

    #: Owner read/write, nothing for group or other — the same mode the
    #: sidecar file carries.
    FILE_MODE: Final[int] = 0o600

    #: Owner may enter and list, nobody else may do either — the sidecar
    #: directory's mode, for the same reason: a ``0o600`` file in a
    #: world-listable directory still leaks every name in it.
    DIRECTORY_MODE: Final[int] = 0o700

    def __init__(self, name: str, path: str | os.PathLike[str]) -> None:
        super().__init__(name)
        self._path = Path(path)

    @property
    def path(self) -> Path:
        """The log file's path.  Not a secret, and safe to report."""
        return self._path

    @classmethod
    def from_env(
        cls,
        env: Mapping[str, str] | None = None,
        *,
        name: str = "sidecar-key-audit",
    ) -> FileAuditSink | None:
        """The file sink this environment names, or ``None`` when unconfigured.

        Reads :data:`AUDIT_LOG_PATH_ENV`; unset or blank means ``None`` — a
        deployment that has not said where the log goes has not configured
        an audit, and guessing a path is how an audit ends up being written
        somewhere nobody reads.  Note the asymmetry with the read path, and
        that it is deliberate: an *absent* sink is discoverable and returns
        ``None``, while a *failed* write to a configured sink raises
        (:class:`AuditSinkError`) and refuses the read.  The two states mean
        different things — "no audit configured here" versus "the audit is
        configured and is not working" — and only the second may ever be
        quiet, which is why only the first is.
        """
        source = os.environ if env is None else env
        raw = (source.get(AUDIT_LOG_PATH_ENV, "") or "").strip()
        if not raw:
            return None
        return cls(name, raw)

    def append(self, record: AuditRecord) -> AuditRecord:
        directory = self._path.parent
        try:
            directory.mkdir(parents=True, exist_ok=True)
            # ``os.O_CREAT``'s mode applies only when the file is created, so
            # a log that already exists with wider bits would keep them
            # forever — corrected on every append, because a dropped-mode
            # restore is a state a deployment drifts into, not one it starts
            # in.  Same for the directory: ``0o600`` inside a world-listable
            # directory still leaks every name in it.
            os.chmod(directory, self.DIRECTORY_MODE)
            if self._path.exists():
                os.chmod(self._path, self.FILE_MODE)
        except OSError as exc:
            raise AuditSinkError(
                f"the audit log directory {directory} could not be prepared: "
                f"{exc} (feature 154)."
            ) from exc
        line = record.to_json().encode("utf-8") + b"\n"
        try:
            descriptor = os.open(
                self._path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, self.FILE_MODE
            )
            try:
                os.write(descriptor, line)
            finally:
                os.close(descriptor)
        except OSError as exc:
            raise AuditSinkError(
                f"the audit log at {self._path} could not be appended to: "
                f"{exc} (feature 154)."
            ) from exc
        return record

    def records(self) -> tuple[AuditRecord, ...]:
        try:
            raw = self._path.read_bytes()
        except FileNotFoundError:
            return ()
        except OSError as exc:
            raise AuditSinkError(
                f"the audit log at {self._path} could not be read: {exc} "
                "(feature 154)."
            ) from exc
        out: list[AuditRecord] = []
        for number, line in enumerate(raw.splitlines(), start=1):
            if not line.strip():
                continue
            try:
                fields = json.loads(line)
            except ValueError as exc:
                raise AuditTrailError(
                    f"line {number} of the audit log at {self._path} is not "
                    "JSON; a record that cannot be read is a hole in the "
                    "chain, and skipping it would report the log intact over "
                    "a line nobody checked (feature 154)."
                ) from exc
            out.append(_record_from_fields(fields, self._path, number))
        return tuple(out)


def _record_from_fields(fields: Any, path: Path, number: int) -> AuditRecord:
    """Rebuild a record from a persisted JSON object, refusing a bad one.

    Split out so :class:`FileAuditSink` and any later file-shaped sink share
    one parser, and so the refusal names the *line* — an operator fixing a
    corrupted log needs to know where the corruption is, and "the log is
    malformed" sends them looking at the whole file.
    """
    if not isinstance(fields, dict):
        raise AuditTrailError(
            f"line {number} of the audit log at {path} is a JSON "
            f"{type(fields).__name__}, not an object; a record is a set of "
            "named fields, and anything else is not a record (feature 154)."
        )
    try:
        return AuditRecord(
            sequence=fields["sequence"],
            previous_digest=fields["previous_digest"],
            requester_account=fields.get("requester_account"),
            granted_account=fields.get("granted_account"),
            decision=fields["decision"],
            reference_label=fields["reference_label"],
            reason=fields["reason"],
            timestamp=fields["timestamp"],
            version=fields.get("version", RECORD_VERSION),
        )
    except KeyError as exc:
        raise AuditTrailError(
            f"line {number} of the audit log at {path} is missing the field "
            f"{exc.args[0]!r}; a record that cannot state its own chain "
            "position and decision cannot be verified, and a record that "
            "cannot be verified is not evidence (feature 154)."
        ) from exc


class AuditLog:
    """The append-only, self-chaining log of null-sidecar-key reads.

    The whole of feature 154's *persists an access audit record*: :meth:`
    append` writes one record, chained to the one before it; :meth:`verify`
    re-derives the chain and refuses a gap, a reorder or an edit;
    :meth:`granted_reads` and :meth:`refused_reads` are the two questions an
    operator actually asks of it.  The log holds no state of its own — the
    sink holds the records — so two logs over one sink see the same chain,
    and a log is as durable as the sink a deployment gave it.

    **What the chain does not do is worth stating as plainly as what it
    does.**  A chain detects a log that was altered *after the fact* — a
    record dropped, reordered, edited, or the whole log re-chained — because
    the alteration has to reproduce digests it did not compute.  It cannot
    detect an attacker who rewrites the log *with* full knowledge from
    :data:`GENESIS` forward, recomputing every digest: nothing stdlib-only
    and store-agnostic can, and a deployment that needs that property needs
    the log shipped to a write-only sink the deployment itself cannot
    rewrite (a KMS audit stream, an append-only relational table with the
    writer's UPDATE revoked).  The chain is the property this module can
    honestly provide on whichever sink a deployment supplies; the sink's own
    immutability is the property only the deployment can.
    """

    __slots__ = ("_sink",)

    def __init__(self, sink: AuditSink) -> None:
        if not isinstance(sink, AuditSink):
            raise AuditTrailError(
                f"an audit log needs a sink, got {type(sink).__name__}. A "
                "log with nowhere to write is the failure feature 154 exists "
                "to make impossible: the record is the feature, and a log "
                "that cannot persist one is a promise rather than an audit "
                "(feature 154)."
            )
        self._sink = sink

    @property
    def sink(self) -> AuditSink:
        """The sink this log appends to — how a failure names its store."""
        return self._sink

    @property
    def records(self) -> tuple[AuditRecord, ...]:
        """Every record the log holds, in append order."""
        return self._sink.records()

    def append(
        self,
        *,
        requester_account: str | None,
        granted_account: str | None,
        decision: str,
        reason: str,
        reference: str | None = None,
        timestamp: float | None = None,
    ) -> AuditRecord:
        """Append one record, chained to the record before it.

        Computes the sequence and the predecessor link from what the sink
        already holds, so a caller cannot invent a position in the log and
        two appenders to one sink cannot both claim to be next.  ``reason``
        is a caller-supplied *vocabulary* phrase — the calling member's own
        short name for the event ("the granted account read the key", "a
        foreign account requested the key") — never free text a caller
        assembles from user input, because the field set is chosen so that
        nothing here can carry a secret and a free-text field would undo
        that.

        ``reference`` is reduced through :func:`describe_reference`, so a
        caller holding the raw ``NULL_SIDECAR_KEY_REF`` value — the ordinary
        case — cannot write the key into the log by handing this method the
        reference the environment gave it.  A caller that has *already*
        reduced the reference (say, through the null oracle member's
        ``KeyReference.scheme_label``) may pass that instead:
        :func:`describe_reference` is idempotent on its own output, so one
        parameter covers both and there is no ``label``-vs-``target``
        argument for a caller to get backwards.

        **A concurrent appender is refused, not silently interleaved.**
        The sequence and the predecessor link are computed from a read of
        the sink, so two appenders racing on one sink can both compute the
        same position and both write — a collision that leaves a log whose
        positions and sequences disagree, which is the state
        :meth:`verify` exists to refuse.  Since the caller here is a
        *key read*, discovering that later is too late: the key would
        already have been served against a record whose chain is broken.
        So the append re-reads the sink and confirms this record landed
        where it was written; a collision raises :class:`AuditSinkError`,
        and the read it belongs to is refused with it.  This is not a lock
        — nothing stdlib-only and cross-process is — it is the check that
        makes the failure *loud at the read* rather than *quiet until an
        audit*.
        """
        held = self._sink.records()
        previous = held[-1].digest() if held else GENESIS
        record = AuditRecord(
            sequence=len(held),
            previous_digest=previous,
            requester_account=requester_account,
            granted_account=granted_account,
            decision=decision,
            reference_label=describe_reference(reference),
            reason=reason,
            timestamp=time.time() if timestamp is None else timestamp,
        )
        written = self._sink.append(record)
        if written is None or written.digest() != record.digest():
            raise AuditSinkError(
                f"the audit sink {self._sink.name!r} did not return the "
                "record it was given; a sink that cannot give back what it "
                "took cannot be trusted to have kept it, and an audit line "
                "the deployment believes exists and does not is worse than "
                "no audit at all (feature 154)."
            )
        self._assert_landed(record)
        return record

    def _assert_landed(self, record: AuditRecord) -> None:
        """Confirm ``record`` is where it was written, or refuse the append.

        The collision check: re-read the sink and require that the record at
        ``record.sequence`` is *this* record.  A racing appender that
        computed the same position wrote first, so the line at that position
        is theirs and this append is refused.  Split out from :meth:`append`
        so the fail-closed rule reads as one named check rather than as a
        tail of inline comparisons, and so :meth:`verify`'s vocabulary stays
        the one place a broken chain is described.
        """
        landed = self._sink.records()
        if record.sequence >= len(landed) or landed[record.sequence].digest() != record.digest():
            raise AuditSinkError(
                f"the audit sink {self._sink.name!r} holds a record at "
                f"position {record.sequence} that is not the one just "
                "written to it: another appender computed the same position "
                "from the same read of the log and wrote first. The two "
                "lines cannot both be the log's record at that position, so "
                "the chain is broken — and because the caller here is a key "
                "read, the read is refused rather than served against a "
                "record that cannot be verified (feature 154)."
            )

    def verify(self) -> tuple[AuditRecord, ...]:
        """Re-derive the chain; refuse a dropped, reordered or edited record.

        Walks the sink's records in order and checks three things: the first
        chains from :data:`GENESIS`, each record's ``previous_digest`` is its
        predecessor's digest, and each record's ``sequence`` is its position.
        The sequence check is not redundant with the link check — a record
        dropped *together with* a re-chain would satisfy the links, and the
        sequence is what catches a log that was rebuilt rather than merely
        edited.

        Returns the records when the chain holds, so a caller that has
        verified can go on to read them; raises :class:`AuditChainError`
        naming the position where it broke, because "the log is corrupt"
        without a line number is not an answer an operator can act on.
        """
        held = self._sink.records()
        expected_previous = GENESIS
        for position, record in enumerate(held):
            if record.sequence != position:
                raise AuditChainError(
                    f"the access audit log at {self._sink.name!r} holds a "
                    f"record at position {position} claiming sequence "
                    f"{record.sequence}; a log whose positions and sequences "
                    "disagree was rebuilt rather than appended to, so the "
                    "lines it holds now cannot be shown to be the lines it "
                    "was written with (feature 154)."
                )
            if record.previous_digest != expected_previous:
                raise AuditChainError(
                    f"the access audit log at {self._sink.name!r} breaks at "
                    f"record {position}: it names predecessor "
                    f"{record.previous_digest[:12]}… and the record before it "
                    f"digests to {expected_previous[:12]}…. A record was "
                    "removed, reordered, or edited — and a log with a hole in "
                    "it cannot answer the one question feature 154 asks of "
                    "it, because the absence of a line no longer means no "
                    "read happened (feature 154)."
                )
            expected_previous = record.digest()
        return held

    def granted_reads(self) -> tuple[AuditRecord, ...]:
        """The reads the one service account was allowed — the expected case."""
        return tuple(r for r in self._sink.records() if r.granted)

    def refused_reads(self) -> tuple[AuditRecord, ...]:
        """The reads a second account attempted — the case the feature exists for.

        The more interesting half of the log.  §7.1 grants the key to
        *exactly one* account, so every record here is a request the
        deployment's rule turned away, and an operator's first question of
        the audit is usually whether there are any at all.
        """
        return tuple(r for r in self._sink.records() if not r.granted)


class KeyReadAudit:
    """The chokepoint: a key read that is audited before it is served.

    Feature 154's *per read* is enforced here rather than at the log, and
    the placement is the design.  A log is passive — a caller writes to it
    or does not, and a caller that does not is precisely the caller an audit
    is for — so the rule is stated as a *wrapper around the read*: :meth:`
    read` is the only way to get the key, it asks the granted account first,
    it writes the record, and only then does it hand back material.  A
    process that reads the sidecar key through this object has an audit line
    by construction; the way to have none is to bypass the object, which is
    a thing a reviewer can see in a diff.

    **The order of operations is the whole contract, and each step is
    load-bearing:**

    1. decide — the account comparison, before anything is served;
    2. record — the write, before anything is served;
    3. serve — the material, only if 2 succeeded.

    Recording *before* serving is what makes the log evidence: a record
    written after the key was handed out would be a record a crash could
    lose, leaving a read that happened with no line and no way to tell.
    And the refusal is recorded too (see :class:`KeyAuditError`), because
    the attempt is the event worth surfacing.

    **An unnamed requester reads as the granted account.**  When the
    deployment has configured *which* account owns the key but a caller
    hands this object no identity, the read is recorded as having been made
    by that account — because it was: the process that resolved the key in
    a deployment naming one account is that account, and a record reading
    ``requester_account: null`` would say the audit does not know who read
    the key.  This is the sibling member's rule verbatim —
    ``nulloracle.keyref.ensure_key`` computes
    ``requester = account if account is not None else granted`` — restated
    here rather than imported, and the two must stay in step: the chokepoint
    and the resolver are two halves of one read, and a log that described
    the same read two ways depending on which half built the object would be
    an audit an operator could not trust.  With *no* account configured
    there is nothing to attribute the read to, and the record says so
    (``None``) rather than inventing one.
    """

    __slots__ = ("_account", "_granted", "_log", "_reference")

    def __init__(
        self,
        log: AuditLog,
        *,
        granted_account: str | None = None,
        account: str | None = None,
        reference: str | None = None,
    ) -> None:
        if not isinstance(log, AuditLog):
            raise AuditTrailError(
                f"a key-read chokepoint needs an audit log, got "
                f"{type(log).__name__}. A chokepoint with nowhere to record "
                "would serve the key un-audited, which is the state feature "
                "154 exists to make impossible — refused at construction, "
                "where the mistake is, rather than at the first read, where "
                "the key would already be out (feature 154)."
            )
        self._log = log
        self._granted = granted_account
        self._account = account
        self._reference = reference

    @classmethod
    def from_env(
        cls, log: AuditLog, env: Mapping[str, str] | None = None
    ) -> KeyReadAudit:
        """The audit this environment configures: account, grant, reference.

        Reads two variables the null oracle member also reads —
        ``NULL_SIDECAR_SERVICE_ACCOUNT`` (the one granted account) and
        ``NULL_SIDECAR_KEY_REF`` (the reference, reduced to a label before it
        reaches the log).  The requesting account is deliberately left
        unnamed: it is derived by :attr:`requester`, which attributes the read
        to the granted account when one is configured.  Naming it here as
        well would be the same rule spelled twice, and the two spellings
        would be free to drift.  A deployment that has named neither gets
        ``None`` for both, which :meth:`read` treats as "the account rule is
        not configured" — the same supported state
        ``nulloracle.keyref.service_account`` documents, in which the
        filesystem mode bits are the whole of the enforcement and the audit
        records the read without adjudicating it.

        Deliberately reads the environment rather than importing the null
        oracle member's ``service_account()``: ``infra/security/`` is outside
        the workspace's import graph by design, so the two spellings of the
        variable names are kept in step by comment and by test, not by a
        cross-workspace import.
        """
        source = os.environ if env is None else env
        granted = (source.get(SERVICE_ACCOUNT_ENV, "") or "").strip() or None
        reference = (source.get(KEY_REF_ENV, "") or "").strip() or None
        return cls(log, granted_account=granted, reference=reference)

    @property
    def log(self) -> AuditLog:
        """The log this chokepoint appends to."""
        return self._log

    @property
    def account(self) -> str | None:
        """The account this chokepoint was built to speak for, as given."""
        return self._account

    @property
    def granted_account(self) -> str | None:
        """The one account the key is granted to, or ``None`` when unconfigured."""
        return self._granted

    @property
    def requester(self) -> str | None:
        """The account the read is *attributed* to — the rule, in one place.

        The identity that decides the read and that the record names.  An
        explicit :attr:`account` wins; otherwise the granted account is it,
        on the reasoning the class docstring gives (a deployment that named
        one account has named the account its own processes run as); with
        neither configured there is no identity and the read is attributed
        to ``None``.

        One property rather than the same conditional at the comparison and
        at the record: the two must agree — a read refused as one account
        and recorded as another would be an audit of a different event than
        the one that happened — and a rule stated once cannot drift from
        itself.
        """
        return self._account if self._account is not None else self._granted

    def read(self, material: bytes, *, timestamp: float | None = None) -> bytes:
        """Audit the read, then return ``material`` — or refuse and audit that.

        ``material`` is the key the caller's backend already resolved (the
        same seam ``nulloracle.keyref.ensure_key(material=…)`` offers): this
        object's job is not to obtain the key but to be the *only* way it
        leaves, so that leaving is recorded.  A caller that has the material
        and does not come through here has bypassed the audit, and no API can
        prevent that — what this object can do is make the audited path the
        ordinary one and the bypass visible.

        Refused when both accounts are configured and the requester is not
        the granted one: the refusal is recorded first (with *both*
        identities, so an operator sees who asked and who holds it), and then
        :class:`KeyAuditError` is raised.  Nothing is returned on the refusal
        path — not an empty bytes, not ``None`` — because a caller that
        mistook a refusal for a key would decrypt with nothing and report the
        sidecar corrupt, which is a different and much worse failure than the
        one that actually happened.
        """
        requester = self.requester
        granted = self._granted
        if requester is not None and granted is not None and requester != granted:
            self._log.append(
                requester_account=requester,
                granted_account=granted,
                decision=AuditDecision.REFUSED,
                reference=self._reference,
                reason=(
                    "a key read was requested by an account that is not the "
                    "one the key is granted to"
                ),
                timestamp=timestamp,
            )
            raise KeyAuditError(
                f"the sidecar key is granted to the service account "
                f"{granted!r} and was requested by {requester!r}; §7.1 seals "
                "the sidecar readable by ONE service account, so the read is "
                "refused — and the refusal is recorded in the audit log "
                "before it is raised, because the attempt is the event an "
                "operator needs to see (feature 154)."
            )
        self._log.append(
            requester_account=requester,
            granted_account=granted,
            decision=AuditDecision.GRANTED,
            reference=self._reference,
            reason=(
                "the account the key is granted to read it"
                if granted is not None
                else "a key read was served with no account granted"
            ),
            timestamp=timestamp,
        )
        return material


def audited_key_read(
    material: bytes,
    *,
    log: AuditLog,
    granted_account: str | None = None,
    account: str | None = None,
    reference: str | None = None,
    timestamp: float | None = None,
) -> bytes:
    """Read the key through an audit, in one call — the functional spelling.

    The same contract as :meth:`KeyReadAudit.read`, for a caller that has no
    reason to hold the object: a function that takes the material, refuses a
    foreign account, records the read, and returns the material.  Provided
    because the seam a caller reaches for should be the *easiest* one — a
    member that offered only a class would find its call sites constructing
    a temporary wrapper and forgetting it, and this way the audited read is
    one call with the log as a keyword argument.
    """
    return KeyReadAudit(
        log,
        granted_account=granted_account,
        account=account,
        reference=reference,
    ).read(material, timestamp=timestamp)
