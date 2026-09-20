"""Feature 148's law: the loop's credentials cannot write the zone.

app_spec.xml, "Trust Zone Isolation & Secrets", feature 148: *System
grants loop-mutated components a credential set that rejects every
write to the immutable zone.*  docs/nullius-tech-architecture.md §2
fixes the control in its "single most important line" — "agents write
to Z1 only, and Z1 has no credential for Z0.  Enforce with filesystem
permissions and network policy, never with prompt instructions.  A
prompt is not a security boundary." — and §1 P1 states the half this
feature owns: the zone's contents are ones "LLM-authored code has no
write credential for".  The sentence decomposes into three claims, each
owned here as a seam rather than a comment:

* **grants loop-mutated components** — the subject, held by
  *membership*, not by name.  §2's table names Z1 "Mutated by the
  loop" — signal code and exploration policy code, written by LLM
  agents — and the committed document
  (:data:`COMMITTED_LOOP_CREDENTIAL_POLICY`) carries the two boxes
  §3's component map draws for that zone, the signal sandbox and the
  policy runtime, the same membership feature 149's committed egress
  policy holds, so a third
  loop-mutated component inherits the law by being *listed*, not by
  someone remembering to copy a rule onto it.  The gate honours the
  same membership: an attempt whose origin the policy does not list is
  answered with :attr:`ZoneWriteReason.UNKNOWN_COMPONENT`, because an
  unlisted component is not a wider grant — it is a component this
  policy vouches for nothing, and nothing is what it gets.

* **a credential set** — the grant's shape, and the reason the law
  below is a law rather than an emptiness.  A credential here is not a
  secret (feature 151 owns those) and not an environment binding
  (feature 153 owns that): it is a *capability set* — named
  credentials (:class:`GrantedCredential`), each holding permissions
  (:class:`Permission`), each permission one place and the operations
  it answers there (:class:`CredentialOperation`).  This is §2's
  "filesystem permissions" half of "enforce with filesystem
  permissions and network policy, never with prompt instructions" —
  and the set is deliberately *full*: the committed document's
  components hold genuine write capabilities, to their own Z1 work
  areas and to the Z3 artifact drop where proposed code lands.  A
  component that can truly write somewhere, and still cannot write
  the zone anywhere in its set, is the feature's own shape; an empty
  grant would satisfy the same sentence by saying nothing.

* **that rejects every write to the immutable zone** — the law, held
  in both tenses.  *Compile-time:* :func:`compile_loop_credential_
  policy` refuses — fail closed, the whole document, not the one
  permission skipped — any permission that carries a write-side
  operation onto any path inside the immutable zone
  (:class:`ZoneWritePermissionRejected`), and onto any path that
  *covers* a zone path, because a grant on the parent directory is a
  write to the zone in disguise.  *Answer-time:*
  :func:`authorize_zone_write` answers every write attempt a
  component makes at the zone with
  :attr:`ZoneWriteReason.NO_WRITE_CREDENTIAL_FOR_IMMUTABLE_ZONE`,
  computed *before* the credential set is consulted, so §2's "Z1 has
  no credential for Z0" outranks everything — even a rogue,
  hand-assembled grant can never read as permission to write the
  zone.  And *every* means every: all eight write-side operations of
  the closed vocabulary, from ``write`` to ``chown``; every spelling
  of a zone path, a trailing slash or a traversal-shaped
  ``/zones/z0/../z0/ledger`` alike, read through the same
  normalization the compile pinned the zone with; from every listed
  component and every unlisted one.  An operation the vocabulary
  cannot even name is not a read, and the zone answers nothing it
  cannot name — the unnamed operation aimed at the zone earns the
  same headline rejection, because a credential set that cannot say
  what an attempt is certifies nothing about it.

**The refusal is raised; the rejection is returned.**  Two audiences,
two shapes, one law — the same discipline feature 149's gate holds.  A
grant document is written by trusted code — an operator, a CI check —
so a document that drifts open is refused with an exception the caller
cannot ignore (:class:`ZoneWritePermissionRejected`, the dual of
feature 156's :class:`infra.security.network_policy.
IngressRuleRejected`).  A write attempt is made by *untrusted* code —
agent-authored, by definition — and arrives in every shape,
well-formed and hostile alike, so the gate *answers* attempts the way
the egress gate answers dial-outs (:func:`infra.security.
sandbox_egress.authorize_egress`): a decision for every attempt,
raised for none, with the rejection computed rather than assumed.  The
consultation is written, not deleted: the gate asks the component's
compiled set whether any credential covers the attempt
(:meth:`ComponentCredentials.permits`), so a reader can see the
allowance branch exists and is reachable — for the work areas the
grant really holds — and that the zone's rejection stands in front of
it rather than in place of it.

**Honest limits.**  This module is the policy-time law, not the
runtime enforcement: at runtime the zone is mounted read-only for
every service (feature 147) and runs under its separate IAM role (§2's
Z0 row: "Human, via signed release only"), so a write the credential
set somehow carried would still meet the mount; and like every Python
object graph, a hand-assembled policy can hold a permission no
compiler would issue.  What holds is that the committed document
cannot drift open without the compile failing, that the gate derives
its answer from the zone and the consulted set rather than a hardcoded
denial, and that even a rogue grant cannot read as permission to write
the zone — the zone's rejection is checked before the set is
consulted, so §2's line outranks everything.  Enforce with filesystem
permissions, never with prompt instructions (§2): "a prompt is not a
security boundary", and this module is the filesystem permission.

Stdlib-only, like the rest of this tree.  Nothing here opens a file;
this module is the grant the loop's components run under and the law
the runtime enforcement is written against, and the artifact
(:data:`COMMITTED_LOOP_CREDENTIAL_POLICY`) is what an operator applies.
"""

from __future__ import annotations

import enum
import json
import posixpath
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Final

__all__ = [
    "COMMITTED_LOOP_CREDENTIAL_POLICY",
    "POLICY_KIND",
    "READ_OPERATIONS",
    "WRITE_OPERATIONS",
    "ComponentCredentials",
    "CredentialOperation",
    "GrantDocumentError",
    "GrantedCredential",
    "ImmutableZone",
    "LoopCredentialError",
    "LoopCredentialPolicy",
    "MissingImmutableZone",
    "Permission",
    "ZoneWriteAttempt",
    "ZoneWriteDecision",
    "ZoneWritePermissionRejected",
    "ZoneWriteReason",
    "authorize_zone_write",
    "committed_loop_credential_policy",
    "compile_loop_credential_policy",
    "load_loop_credential_policy",
]

#: What kind of document this module compiles.  A fixed marker, checked
#: at compile time, so a JSON file that happens to carry a
#: ``components`` key cannot be read as the loop's credential grant: a
#: document that does not say what it is cannot be trusted to say what
#: it allows.
POLICY_KIND: Final[str] = "loop-credentials"

#: The committed credential grant of the loop-mutated components — the
#: JSON artifact this feature's law is written against, and the thing
#: an operator applies.  ``infra/security/`` is shared by the whole
#: "Trust Zone Isolation & Secrets" category, so the document is named
#: for whose credentials it holds, the way the egress document beside
#: it is named for the surface it empties.
COMMITTED_LOOP_CREDENTIAL_POLICY: Final[Path] = Path(__file__).with_name(
    "loop_credential_policy.json"
)


class CredentialOperation(enum.StrEnum):
    """The closed vocabulary of operations a permission may answer.

    A credential set grants *operations on paths*, and the grant is
    only auditable if the operations are a closed set: "every write"
    must enumerate something, or a spelling nobody listed could slip
    past the law as neither read nor write.  The vocabulary splits in
    two, and the split *is* the feature — the read side is everything
    the zone may be asked through, the write side is everything the
    law refuses onto it:

    * read side — :attr:`READ`, :attr:`LIST`, :attr:`STAT`: the
      operations that answer with the zone's content and leave it
      exactly as found.
    * write side — :attr:`WRITE`, :attr:`APPEND`, :attr:`CREATE`,
      :attr:`DELETE`, :attr:`RENAME`, :attr:`TRUNCATE`,
      :attr:`CHMOD`, :attr:`CHOWN`: the operations that change the
      zone, its bytes or its metadata — the ledger's appends and the
      snapshot's seals included, because an append-only store is
      still a store nothing but the release process may append to.

    An operation name outside this vocabulary is refused by the
    compile, never dropped: silently discarding an unrecognised token
    would let a misspelled ``write`` read as a compliant grant, which
    is the one failure this feature exists to prevent — the same
    discipline feature 152 holds over exchange-key permissions.
    """

    #: Read the bytes of a place.  The zone answers this; §2's Z0 row
    #: is read-only, not unreadable.
    READ = "read"

    #: List the members of a place.  A directory read that changes
    #: nothing.
    LIST = "list"

    #: Read the metadata of a place — size, mode, the hash a pinned
    #: image is checked by.
    STAT = "stat"

    #: Overwrite the bytes of a place.
    WRITE = "write"

    #: Add bytes to the end of a place.  The ledger's own verb — and
    #: the ledger is Z0, so even this is refused onto the zone.
    APPEND = "append"

    #: Bring a place into existence.
    CREATE = "create"

    #: Take a place out of existence.
    DELETE = "delete"

    #: Change what a place is called — a write by another name, since
    #: the zone's names are part of its pinned shape.
    RENAME = "rename"

    #: Cut a place shorter.
    TRUNCATE = "truncate"

    #: Change a place's permission bits.  Refused onto the zone twice
    #: over: it is a change, and it is the change that would try to
    #: unmake the read-only mount itself.
    CHMOD = "chmod"

    #: Change who owns a place.
    CHOWN = "chown"

    @classmethod
    def read_vocabulary(cls) -> tuple[CredentialOperation, ...]:
        """The read side of the vocabulary, in declaration order."""
        return (cls.READ, cls.LIST, cls.STAT)

    @classmethod
    def write_vocabulary(cls) -> tuple[CredentialOperation, ...]:
        """The write side of the vocabulary, in declaration order."""
        return (
            cls.WRITE,
            cls.APPEND,
            cls.CREATE,
            cls.DELETE,
            cls.RENAME,
            cls.TRUNCATE,
            cls.CHMOD,
            cls.CHOWN,
        )

    @property
    def is_write(self) -> bool:
        """Whether this operation changes what it answers.

        Computed from the split, not restated per member, so the two
        sides can never disagree with the property that reads them —
        one list is the truth, the other two are views of it.
        """
        return self in type(self).write_vocabulary()


#: The read side of the vocabulary as plain strings — the spelling an
#: *attempt* carries, held here so the gate can classify untrusted
#: input without parsing it into anything: an operation that is not one
#: of these is not a read, whatever else it is.
READ_OPERATIONS: Final[frozenset[str]] = frozenset(
    operation.value for operation in CredentialOperation.read_vocabulary()
)

#: The write side of the vocabulary as plain strings — the auditable
#: form of "every write": eight named operations, and the compile
#: refuses each of them onto the zone.
WRITE_OPERATIONS: Final[frozenset[str]] = frozenset(
    operation.value for operation in CredentialOperation.write_vocabulary()
)


class LoopCredentialError(Exception):
    """Base of the loop-credential taxonomy.

    One base class so a caller — a CI check that recompiles the
    committed grant, an operator script proposing a change to it, a
    renderer about to print the grant — can catch every failure of the
    compile path with a single ``except``.  The subclasses split by
    *which contract* was violated, never by which line of code failed,
    in the same discipline as :mod:`infra.security.network_policy`'s
    and :mod:`infra.security.sandbox_egress`'s taxonomies.
    """


class GrantDocumentError(LoopCredentialError):
    """The document is not a loop credential grant at all.

    A malformed zone block, an absent credentials half, a duplicate
    component or credential name, an operation outside the closed
    vocabulary, a path that is not absolute.  The compiler fails
    closed on all of them: a document it cannot read completely is a
    document it will not partially trust.
    """


class MissingImmutableZone(LoopCredentialError):
    """A loop credential grant that names no immutable zone.

    The feature's law is named for the place it protects — every write
    to the immutable zone — and a grant that cannot say which paths
    are the zone could never recognize the write it must refuse: it
    would compile happily with a write permission sitting on
    ``/zones/z0``, because nothing in the document said that path was
    Z0.  Refused at compile time, fail closed — the same stance as
    feature 149's :class:`infra.security.sandbox_egress.
    MissingDataLake`, which refuses an egress policy that cannot
    recognize the attempt its rejection is named for.
    """


class ZoneWritePermissionRejected(LoopCredentialError):
    """The law: a loop-mutated component's credential writes the zone.

    Raised by :func:`compile_loop_credential_policy` for any
    write-side operation on any path inside the immutable zone, or on
    any path that covers one — a grant on the parent directory is a
    write to the zone in disguise.  The whole document is refused, not
    the one permission skipped, because a grant applied with the
    permission silently dropped is a grant whose file and whose
    component disagree, and the disagreement is where the next drift
    lives.  §2's line is absolute — "agents write to Z1 only, and Z1
    has no credential for Z0" — so there is no zone path and no write
    spelling any component could earn, not the trial ledger whose
    whole design is append-only, not a scratch file nobody reads.
    """


def _require_mapping(value: Any, what: str) -> Mapping[str, Any]:
    """Return ``value`` as a string-keyed mapping, refusing anything else."""
    if not isinstance(value, Mapping):
        raise GrantDocumentError(
            f"{what} must be a mapping, got {type(value).__name__}: "
            f"{value!r}. A loop credential grant is a structured "
            f"document, and a compiler that guessed at the meaning of a "
            f"stray list or string would be writing policy rather than "
            f"reading it — it is refused instead, fail closed (feature "
            f"148: the loop's credentials reject every write to the "
            f"immutable zone only if the compile read every capability "
            f"it holds)."
        )
    return value


def _require_str(value: Any, what: str) -> str:
    """Return ``value`` as a non-empty string, refusing anything else."""
    if not isinstance(value, str) or not value:
        raise GrantDocumentError(
            f"{what} must be a non-empty string, got {value!r}. The "
            f"grant names its zone, its components, its credentials and "
            f"the operations each answers; a blank or non-string name is "
            f"not a name, and the compiler will not invent one "
            f"(feature 148)."
        )
    return value


def _require_list(value: Any, what: str) -> Sequence[Any]:
    """Return ``value`` as a list, refusing anything else.

    For the document's enumerations — zone paths, components,
    credentials, permissions, operations.  A string is refused too,
    because a bare string *iterates*, and a compiler that read one as
    a list of its characters would be granting capabilities spelled by
    an accident.
    """
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise GrantDocumentError(
            f"{what} must be a list, got {value!r}. The grant's "
            f"enumerations are lists, and anything else — a bare "
            f"string especially, which iterates as its characters — "
            f"cannot be read as one without inventing content the "
            f"document does not carry (feature 148)."
        )
    return value


def _normalized_absolute_path(value: Any, what: str) -> str:
    """Return ``value`` as a canonical absolute POSIX path.

    Absolute, because the credential vocabulary names *places* and a
    relative place is wherever a hostile reader's working directory
    left it — a permission that moves with the reader is not a
    permission, it is an accident.  Normalized, so ``..`` and ``.``
    and a trailing slash collapse before the document is trusted: the
    compile pins the zone and the permissions in one canonical
    spelling, and every later containment question is answered in it.
    A path that will not canonicalize — the POSIX ``//`` prefix the
    normalization preserves — is refused rather than carried.
    """
    raw = _require_str(value, what)
    if not raw.startswith("/"):
        raise GrantDocumentError(
            f"{what} must be an absolute path starting with '/', got "
            f"{raw!r}. The grant's paths name places, not positions "
            f"relative to whoever reads them, and a relative path in a "
            f"credential is a capability whose meaning changes with the "
            f"reader's working directory — refused rather than guessed "
            f"(feature 148)."
        )
    normalized = posixpath.normpath(raw)
    if normalized.startswith("//"):
        raise GrantDocumentError(
            f"{what} is {raw!r}, which normalizes to {normalized!r} — a "
            f"path POSIX leaves deliberately implementation-defined, "
            f"and a path the grant cannot canonically name is one whose "
            f"containment the policy could only guess at. Refused "
            f"(feature 148)."
        )
    return normalized


def _at_or_under(outer: str, inner: str) -> bool:
    """Whether canonical absolute ``inner`` is ``outer`` or lies under it.

    Segment-wise, so ``/zones/z0-sidecar`` is a neighbour, not a child
    of ``/zones/z0`` — and the filesystem root is handled for what it
    is, the one prefix whose separator-appended form (``//``) matches
    nothing: everything absolute lies under ``/``.
    """
    if inner == outer:
        return True
    if outer == "/":
        return inner.startswith("/")
    return inner.startswith(outer + "/")


class ImmutableZone:
    """The immutable zone's geometry: its name and its member roots.

    The place the feature's law protects, held as the union of rooted
    paths — the deployment's spelling of §2's Z0 contents (the
    snapshots, the evaluator, the cost model, the contract, the null
    oracle with its sidecar key, the trial ledger).  Recognition is
    the whole job: the compile cannot refuse a write onto the zone and
    the gate cannot answer one with the zone's own words unless the
    document said which paths are the zone, which is why a document
    without this block is refused (:class:`MissingImmutableZone`)
    rather than compiled with the law quietly unread.

    Roots are canonicalized at compile time and never re-examined:
    every containment question below is a segment-wise comparison
    against a pinned spelling, so no attempt's shape can move the
    boundary.
    """

    __slots__ = ("name", "paths")

    def __init__(
        self, *, name: str, paths: tuple[str, ...]
    ) -> None:
        self.name = name
        self.paths = paths

    def covers(self, path: Any) -> bool:
        """Whether ``path`` lies inside the immutable zone.

        The attempt's spelling is normalized before it is compared —
        a traversal-shaped ``/zones/z0/../z0/ledger`` is the ledger,
        and a trailing slash is the same place — so containment is
        decided on where the path *resolves*, not on how it was typed.
        A path that is not absolute resolves nowhere the zone pinned,
        so it is not inside; the gate answers it by the consultation
        instead, which no absolute-only permission can ever match,
        and the attempt is rejected either way.  Containment is
        segment-wise: ``/zones/z0-sidecar`` is a neighbour, not a
        member — the safe direction is the exact one, because the
        gate's fall-through for a non-member is itself a rejection.
        """
        if not isinstance(path, str) or not path.startswith("/"):
            return False
        candidate = posixpath.normpath(path)
        if candidate.startswith("//"):
            # A path POSIX leaves implementation-defined resolves
            # nowhere this policy pinned; not inside, and the
            # consultation cannot match it either.
            return False
        return any(_at_or_under(root, candidate) for root in self.paths)

    def first_path_covering(self, path: str) -> str | None:
        """The first member root that contains ``path``, or ``None``.

        The compile's naming helper: the refusal cites the zone member
        the offending permission touched, in document order, so the
        drift is findable in the file it was written in.
        """
        candidate = posixpath.normpath(path)
        for root in self.paths:
            if _at_or_under(root, candidate):
                return root
        return None

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return f"ImmutableZone(name={self.name!r}, paths={self.paths!r})"


class Permission:
    """One credential's capability over one place.

    A path, canonicalized at compile time, and the closed set of
    operations the credential answers there — the smallest unit the
    law reasons about, and the only unit that can hold a write.  The
    operations are held as their string values, the spelling an
    attempt arrives in, so the gate's consultation is a plain
    comparison with no conversion an untrusted shape could trip on.
    """

    __slots__ = ("operations", "path")

    def __init__(
        self, *, path: str, operations: frozenset[str]
    ) -> None:
        self.path = path
        self.operations = operations

    def write_operations(self) -> tuple[str, ...]:
        """The write-side operations this permission carries.

        In vocabulary order, so a refusal naming them reads the same
        way every time.  Empty for a read-only permission — most of
        them, under this law.
        """
        return tuple(
            operation.value
            for operation in CredentialOperation.write_vocabulary()
            if operation.value in self.operations
        )

    def covers(self, path: Any) -> bool:
        """Whether ``path`` lies at or under this permission's place.

        The same segment-wise containment the zone matches by, read in
        this direction to answer the gate's consultation: an attempt
        at ``/zones/z1/signal-sandbox/work/prop-7.py`` matches the
        permission on ``/zones/z1/signal-sandbox/work``.
        """
        if not isinstance(path, str) or not path.startswith("/"):
            return False
        candidate = posixpath.normpath(path)
        if candidate.startswith("//"):
            return False
        return _at_or_under(self.path, candidate)

    def permits(self, operation: Any) -> bool:
        """Whether this permission answers ``operation`` here.

        A plain membership test — the closed vocabulary was settled at
        compile time, so the consultation has nothing left to decide
        but whether this operation is one of the ones granted.
        """
        return operation in self.operations

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return (
            f"Permission(path={self.path!r}, "
            f"operations={sorted(self.operations)!r})"
        )


class GrantedCredential:
    """One named credential of a component's set.

    The unit a deployment issues and revokes — a role, a scoped token
    — held here as its name and its permissions.  The grant is a
    *set* of these deliberately: a component whose capabilities arrive
    as one named credential per job has a set whose each member is
    auditable alone, and the law below is checked per permission, so
    no member of the set can hold what the set may not.
    """

    __slots__ = ("name", "permissions")

    def __init__(
        self, *, name: str, permissions: tuple[Permission, ...]
    ) -> None:
        self.name = name
        self.permissions = permissions

    def grant_for(
        self, path: Any, operation: Any
    ) -> Permission | None:
        """The permission that covers ``(path, operation)``, or ``None``.

        The consultation, returning its evidence: the gate's allowed
        decision names the permission that earned it, the way its
        zone rejection names the zone that forbade it.
        """
        for permission in self.permissions:
            if permission.covers(path) and permission.permits(operation):
                return permission
        return None

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return (
            f"GrantedCredential(name={self.name!r}, "
            f"permissions={self.permissions!r})"
        )


class ComponentCredentials:
    """One loop-mutated component's compiled credential set.

    What :func:`compile_loop_credential_policy` hands out per
    component — and the object the gate consults, so its answers are
    *derived* from the compiled set rather than hardcoded.
    :meth:`permits` is a real consultation over :attr:`credentials`;
    the compiler holds every write-side permission in them outside the
    zone (refusing any document that would put one inside), so under
    every compiled policy the consultation can allow a work-area write
    and can never allow a zone one.  A test can build a set with a
    zone write by hand to prove the derivation is real — and the
    gate's answer on such a set is itself the audit finding, because
    no compiled policy can produce it.
    """

    __slots__ = ("credentials", "name")

    def __init__(
        self,
        *,
        name: str,
        credentials: tuple[GrantedCredential, ...],
    ) -> None:
        self.name = name
        self.credentials = credentials

    def grant_for(
        self, path: Any, operation: Any
    ) -> GrantedCredential | None:
        """The credential whose permission covers the attempt, if any.

        First match in document order, so the evidence an allowed
        decision cites is the first grant the document wrote.
        """
        for credential in self.credentials:
            if credential.grant_for(path, operation) is not None:
                return credential
        return None

    def permits(self, path: Any, operation: Any) -> bool:
        """Whether any credential in the set covers ``(path, operation)``.

        Computed, never assumed: ``any`` over the compiled credentials,
        each asked for the permission that covers the attempt.  The
        empty set answers ``False`` for everything — which is a legal
        compiled shape (a component granted no credentials at all
        rejects every zone write vacuously) but one the document must
        *write*, not one absence smuggled in for it.
        """
        return self.grant_for(path, operation) is not None

    def write_targets(self) -> tuple[str, ...]:
        """The distinct places this set may write, in document order.

        The inspectable form of the grant's promise: where the
        component's write capabilities actually live — its Z1 work
        area, the Z3 artifact drop — because under a compiled policy
        no target is inside the immutable zone, and an operator (or a
        test) can check that claim against the compiled set rather
        than take it from the prose.
        """
        targets: list[str] = []
        for credential in self.credentials:
            for permission in credential.permissions:
                if permission.write_operations() and (
                    permission.path not in targets
                ):
                    targets.append(permission.path)
        return tuple(targets)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return (
            f"ComponentCredentials(name={self.name!r}, "
            f"credentials={self.credentials!r})"
        )


class LoopCredentialPolicy:
    """A compiled grant: the zone named, every component's set lawful.

    What :func:`compile_loop_credential_policy` returns is not the
    document — it is the document *plus* the guarantee that no
    credential of no component carries a write onto the immutable
    zone.  Holders of a :class:`LoopCredentialPolicy` (the gate, an
    operator script, a CI check that recompiles the committed
    artifact) cite that guarantee rather than re-derive it, which is
    why the gate's zone rejection can say "the component's credential
    set holds no write capability for the immutable zone" and mean
    it.
    """

    __slots__ = ("_components", "immutable_zone", "kind")

    def __init__(
        self,
        *,
        kind: str,
        immutable_zone: ImmutableZone,
        components: dict[str, ComponentCredentials],
    ) -> None:
        self.kind = kind
        self.immutable_zone = immutable_zone
        self._components = components

    def component(self, name: str) -> ComponentCredentials | None:
        """The named component's credential set, or ``None`` — the
        gate decides what an unknown origin means (a rejection), not
        the lookup."""
        return self._components.get(name)

    def components(self) -> tuple[ComponentCredentials, ...]:
        """Every loop-mutated component the grant covers, in document
        order."""
        return tuple(self._components.values())

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return (
            f"LoopCredentialPolicy(kind={self.kind!r}, "
            f"immutable_zone={self.immutable_zone!r})"
        )


def compile_loop_credential_policy(document: Any) -> LoopCredentialPolicy:
    """Compile a loop credential grant, refusing one that writes the zone.

    The seam the whole feature turns on.  The document is read whole —
    marker, immutable zone, components with their credentials and
    permissions — each permission held to the law *after* it parses so
    the refusal names a capability that actually exists (a validated
    path, operations of the closed vocabulary), and only then is a
    :class:`LoopCredentialPolicy` handed out.  A refusal propagates as
    an exception, so a caller cannot accidentally continue with a
    half-trusted grant: the document that would have written the zone
    is never applied, which is the compile-time half of "System
    grants ... a credential set that rejects every write to the
    immutable zone" (feature 148).
    """
    doc = _require_mapping(document, "loop credential grant document")
    marker = _require_str(doc.get("policy"), "loop credential grant 'policy'")
    if marker != POLICY_KIND:
        raise GrantDocumentError(
            f"a loop credential grant must declare itself "
            f"{POLICY_KIND!r}, got {marker!r}. A document that does not "
            f"say what it is cannot be trusted to say what it allows, "
            f"and a stray JSON file carrying a 'components' key is not "
            f"this grant — refused, fail closed (feature 148)."
        )

    immutable_zone = _compile_immutable_zone(doc.get("immutable_zone"))

    raw_components = doc.get("components")
    if raw_components is None:
        raise GrantDocumentError(
            "the grant's 'components' is absent. The loop-mutated "
            "components are the law's whole subject — 'grants "
            "loop-mutated components a credential set' — and a document "
            "that cannot enumerate them cannot be compiled (feature "
            "148)."
        )
    listed = _require_list(
        raw_components, "the grant's 'components'"
    )

    components: dict[str, ComponentCredentials] = {}
    for index, raw_component in enumerate(listed):
        what = f"component #{index + 1}"
        block = _require_mapping(raw_component, what)
        name = _require_str(block.get("name"), f"{what} 'name'")
        what = f"component {name!r}"
        if name in components:
            raise GrantDocumentError(
                f"{what} appears twice in the grant. Two blocks with one "
                f"name is not two components, it is one component "
                f"described twice — and the applied grant would be "
                f"whichever block came last, which is drift with extra "
                f"steps. Refused (feature 148)."
            )
        components[name] = _compile_component_credentials(
            block, what, immutable_zone
        )

    return LoopCredentialPolicy(
        kind=marker, immutable_zone=immutable_zone, components=components
    )


def _compile_immutable_zone(raw: Any) -> ImmutableZone:
    """Compile the immutable zone block, refusing a grant that omits it.

    The zone is the place the feature's law is named for; see
    :class:`MissingImmutableZone` for why a grant that cannot
    recognize the write it must refuse is refused rather than
    compiled.
    """
    if raw is None:
        raise MissingImmutableZone(
            "the loop credential grant names no immutable zone. The "
            "feature's law is named for the place it protects — every "
            "write to the immutable zone — and a grant that cannot say "
            "which paths are the zone could never recognize the write "
            "it must refuse: it would compile happily with a write "
            "permission sitting on a zone path, because nothing in the "
            "document said the path was Z0. Refused at compile time, "
            "fail closed (feature 148)."
        )
    block = _require_mapping(raw, "the grant's 'immutable_zone'")
    name = _require_str(block.get("name"), "the immutable zone's 'name'")
    raw_paths = block.get("paths")
    if (
        not isinstance(raw_paths, Sequence)
        or isinstance(raw_paths, (str, bytes))
        or not raw_paths
    ):
        raise GrantDocumentError(
            f"the immutable zone's 'paths' must be a non-empty list of "
            f"rooted paths, got {raw_paths!r}. The zone is a place, "
            f"named by the roots that make it up (§2's Z0 contents: the "
            f"snapshots, the evaluator, the cost model, the contract, "
            f"the null oracle, the trial ledger), and a zone with no "
            f"paths named is one the law protects nowhere (feature "
            f"148)."
        )
    paths: list[str] = []
    for index, raw_path in enumerate(raw_paths):
        path = _normalized_absolute_path(
            raw_path, f"the immutable zone's path #{index + 1}"
        )
        if path == "/":
            raise GrantDocumentError(
                "the immutable zone's '/' path makes the whole "
                "filesystem the zone. The zone is a bounded place — §2 "
                "lists its contents — and a zone whose root is "
                "everything has confused the zone's geometry with the "
                "posture the law already holds for every component. "
                "Refused so the document keeps saying which place is "
                "immutable (feature 148)."
            )
        for pinned in paths:
            if path == pinned or path.startswith(pinned + "/") or (
                pinned.startswith(path + "/")
            ):
                raise GrantDocumentError(
                    f"the immutable zone's paths pin {path!r} and "
                    f"{pinned!r}, one inside the other. The zone is a "
                    f"union of roots, and a member inside a member adds "
                    f"no place while suggesting the smaller one is "
                    f"separately negotiable — the zone is not à la "
                    f"carte. Refused (feature 148)."
                )
        paths.append(path)
    return ImmutableZone(name=name, paths=tuple(paths))


def _compile_component_credentials(
    block: Mapping[str, Any], what: str, zone: ImmutableZone
) -> ComponentCredentials:
    """Compile one component's credential set, holding it to the law.

    Structure first — the credentials list must be written, empty or
    not; names unique; every permission a canonical path and
    operations of the closed vocabulary — then the law, per
    permission, after it parses: any write-side operation onto a path
    inside the zone, or onto a path that covers one, refuses the whole
    document (:class:`ZoneWritePermissionRejected`).
    """
    raw_credentials = block.get("credentials")
    if raw_credentials is None:
        raise GrantDocumentError(
            f"{what} 'credentials' is absent. An empty list is a "
            f"component granted nothing at all — a legal shape, since "
            f"it rejects every zone write vacuously — but it must be "
            f"written: a compiler that read an absent half as an empty "
            f"one would be turning silence into the grant's strongest "
            f"promise. 'Absent' and 'held empty on purpose' are "
            f"different promises, and only the second one is a grant "
            f"(refused, fail closed — feature 148)."
        )
    listed = _require_list(raw_credentials, f"{what} 'credentials'")

    names: set[str] = set()
    credentials: list[GrantedCredential] = []
    for index, raw_credential in enumerate(listed):
        cred_what = f"{what} credential #{index + 1}"
        cred_block = _require_mapping(raw_credential, cred_what)
        cred_name = _require_str(
            cred_block.get("name"), f"{cred_what} 'name'"
        )
        cred_what = f"{what} credential {cred_name!r}"
        if cred_name in names:
            raise GrantDocumentError(
                f"{cred_what} appears twice in the component's "
                f"credentials. One name is one credential — the unit a "
                f"deployment issues and revokes — and two blocks "
                f"sharing a name is whichever came last, which is drift "
                f"with extra steps. Refused (feature 148)."
            )
        names.add(cred_name)
        credentials.append(
            _compile_permissions(cred_block, cred_what, zone)
        )

    return ComponentCredentials(
        name=block["name"], credentials=tuple(credentials)
    )


def _compile_permissions(
    cred_block: Mapping[str, Any], cred_what: str, zone: ImmutableZone
) -> GrantedCredential:
    """Compile one credential's permissions, holding each to the law.

    The vocabulary is closed: an operation name outside it is refused,
    never dropped, because silently discarding an unrecognised token
    would let a misspelled ``write`` read as a compliant grant.  A
    permission with no operations is refused for the same reason the
    absent lists are — a permission that grants nothing is not a
    permission but a placeholder, and the grant does not deal in
    placeholders.
    """
    raw_permissions = cred_block.get("permissions")
    if raw_permissions is None:
        raise GrantDocumentError(
            f"{cred_what} 'permissions' is absent. An empty list is a "
            f"credential that holds nothing — a legal shape, written "
            f"explicitly — but absence is not emptiness, and a compiler "
            f"that read one as the other would be inventing the grant's "
            f"shape rather than reading it (refused, fail closed — "
            f"feature 148)."
        )
    listed = _require_list(raw_permissions, f"{cred_what} 'permissions'")

    permissions: list[Permission] = []
    for index, raw_permission in enumerate(listed):
        perm_what = f"{cred_what} permission #{index + 1}"
        perm_block = _require_mapping(raw_permission, perm_what)
        path = _normalized_absolute_path(
            perm_block.get("path"), f"{perm_what} 'path'"
        )
        raw_operations = perm_block.get("operations")
        if (
            not isinstance(raw_operations, Sequence)
            or isinstance(raw_operations, (str, bytes))
            or not raw_operations
        ):
            raise GrantDocumentError(
                f"{perm_what} 'operations' must be a non-empty list of "
                f"the vocabulary's names, got {raw_operations!r}. A "
                f"permission that answers no operation grants nothing "
                f"and says it does, and the grant does not deal in "
                f"placeholders (feature 148)."
            )
        operations: list[str] = []
        for raw_operation in raw_operations:
            name = _require_str(raw_operation, f"{perm_what} operation")
            if name not in READ_OPERATIONS | WRITE_OPERATIONS:
                raise GrantDocumentError(
                    f"{perm_what} carries operation {name!r}, which is "
                    f"not of the credential vocabulary "
                    f"({', '.join(op.value for op in CredentialOperation)}"
                    f"). An unknown name is refused, never dropped: "
                    f"silently discarding an unrecognised token would "
                    f"let a misspelled 'write' read as a compliant "
                    f"grant, which is the one failure this feature "
                    f"exists to prevent (feature 148)."
                )
            if name not in operations:
                operations.append(name)
        permission = Permission(
            path=path, operations=frozenset(operations)
        )

        _refuse_zone_writes(permission, perm_what, zone)
        permissions.append(permission)

    return GrantedCredential(
        name=cred_block["name"], permissions=tuple(permissions)
    )


def _refuse_zone_writes(
    permission: Permission, perm_what: str, zone: ImmutableZone
) -> None:
    """Refuse a permission that writes the immutable zone, any way round.

    Both directions are the law's: a path *inside* a zone member is a
    write to the zone's content, and a path *covering* a zone member —
    the parent directory, the filesystem root short of ``/`` itself —
    is a write to the zone in disguise, because a capability on the
    parent reaches every child.  The first zone member the permission
    touches is named in document order, so the drift is findable in
    the file it was written in.
    """
    writes = permission.write_operations()
    if not writes:
        return

    for root in zone.paths:
        inside = _at_or_under(root, permission.path)
        covering = _at_or_under(permission.path, root)
        if not (inside or covering):
            continue
        if inside:
            direction = "inside the immutable zone"
        else:
            direction = (
                f"covering the immutable zone's {root!r} — a grant on "
                f"the parent is a write to the zone in disguise"
            )
        raise ZoneWritePermissionRejected(
            f"{perm_what} carries the write operation(s) "
            f"{', '.join(repr(op) for op in writes)} on {permission.path!r}, "
            f"{direction} ({zone.name!r}, member {root!r}). §2's line is "
            f"absolute — agents write to Z1 only, and Z1 has no "
            f"credential for Z0 — so there is no zone path and no write "
            f"spelling a loop-mutated component could earn: not the "
            f"trial ledger, whose whole design is append-only but whose "
            f"appends are the release process's to make; not a scratch "
            f"file nobody reads; not the permission bits that would try "
            f"to unmake the read-only mount itself. The whole document "
            f"is refused, not the permission skipped — a grant applied "
            f"with the write silently dropped is one whose file and "
            f"whose component disagree, and that disagreement is where "
            f"the next drift lives (feature 148: the credential set "
            f"rejects every write to the immutable zone, and a set "
            f"that holds one is not the set the system grants)."
        )


class ZoneWriteReason(enum.StrEnum):
    """Why a decision came out the way it did — the audit vocabulary.

    One enumeration carries the acceptance and the rejection reasons,
    because a decision's reason is one fact with two polarities, and
    the audit line should read the same either way:
    ``no-write-credential-for-immutable-zone`` is §2's own claim —
    "Z1 has no credential for Z0" — not a rule this policy invented.
    """

    #: Rejected: the attempt is a write at the immutable zone, and the
    #: component's credential set holds no write capability for it —
    #: §2's "Z1 has no credential for Z0", the feature's own sentence.
    #: Checked before the set is consulted, so it outranks everything.
    NO_WRITE_CREDENTIAL_FOR_IMMUTABLE_ZONE = (
        "no-write-credential-for-immutable-zone"
    )

    #: Rejected: the attempt's origin is not a component the grant
    #: covers.  An unlisted component is not a wider grant; it is a
    #: component this policy vouches for nothing, and nothing is what
    #: it gets.
    UNKNOWN_COMPONENT = "unknown-component"

    #: Rejected: the origin is known and the place is not the zone,
    #: but no credential in the set covers this attempt.  The set is
    #: real and finite — it grants the work areas it grants — and an
    #: attempt outside both the zone and the grant falls here.
    NO_PERMISSION = "no-permission"

    #: Admitted by a permission of the component's compiled set.  The
    #: reachable branch for the grant's legitimate writes — the Z1
    #: work areas, the Z3 artifact drop — and *only* for them: no
    #: compiled policy can produce this reason for a path inside the
    #: immutable zone, by two independent mechanisms (the compile
    #: refuses the permission; the gate checks the zone first), so an
    #: allowed decision aimed at the zone is itself the audit finding.
    BY_PERMISSION = "by-permission"


class ZoneWriteAttempt:
    """One write attempt from a loop-mutated component, as presented.

    Deliberately unvalidated beyond assignment: the gate models what
    agent-authored code reached for, hostile shapes included, and
    *answers* them rather than refusing to parse them — the same
    stance :class:`infra.security.sandbox_egress.EgressAttempt` takes
    for dial-outs.  ``origin`` names the component the attempt claims
    to write from, ``path`` is the place it aimed at in whatever
    spelling it used, and ``operation`` is the operation it asked for
    by name — the three facts every reason below reads.
    """

    __slots__ = ("operation", "origin", "path")

    def __init__(
        self, *, origin: str, path: str, operation: str
    ) -> None:
        self.origin = origin
        self.path = path
        self.operation = operation

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return (
            f"ZoneWriteAttempt(origin={self.origin!r}, "
            f"path={self.path!r}, operation={self.operation!r})"
        )


class ZoneWriteDecision:
    """The gate's whole answer: allowed, why, and in what words.

    ``allowed`` is typed as a bool because the decision is the audit
    record a caller reads, and "was it allowed" is the question an
    auditor asks of any gate; under this law the value is ``True``
    exactly when a permission of the compiled set covers the attempt
    and the attempt was not aimed at the immutable zone.  ``detail``
    carries the operator-facing sentence — the one place the
    mechanism explains itself at answer time, naming the origin, the
    place, the operation, and the zone or the permission that decided.
    """

    __slots__ = ("allowed", "detail", "reason")

    def __init__(
        self, *, allowed: bool, reason: ZoneWriteReason, detail: str
    ) -> None:
        self.allowed = allowed
        self.reason = reason
        self.detail = detail

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return f"ZoneWriteDecision(allowed={self.allowed}, reason={self.reason!r})"


def authorize_zone_write(
    attempt: ZoneWriteAttempt, policy: LoopCredentialPolicy
) -> ZoneWriteDecision:
    """Answer one write attempt from a loop-mutated component.

    The order of the checks is the order of the feature's sentence.
    The origin is settled first — the gate answers for the compiled
    grant's components, and an unknown origin has no credential set to
    be evaluated against.  The zone is settled second, *before* the
    set is consulted: the rejection named for the immutable zone is
    the feature's own headline, and §2's "Z1 has no credential for Z0"
    outranks everything — even a rogue, hand-assembled permission can
    never read as write access to the zone.  Everything else is
    settled by the consultation, which the compiler kept lawful, so
    the work areas the grant really holds are allowed and everything
    else falls out the bottom rejected.
    """
    component = policy.component(attempt.origin)
    if component is None:
        return ZoneWriteDecision(
            allowed=False,
            reason=ZoneWriteReason.UNKNOWN_COMPONENT,
            detail=(
                f"write attempt claims origin {attempt.origin!r}, which "
                f"is not a loop-mutated component of grant "
                f"{policy.kind!r}. The gate answers for the compiled "
                f"grant and nothing else; an origin outside it has no "
                f"credential set to be evaluated against and holds no "
                f"credential at all — an unlisted component is not a "
                f"wider grant, it is a component this policy vouches "
                f"for nothing, and nothing is what it gets (feature "
                f"148)."
            ),
        )

    zone = policy.immutable_zone
    aimed_at_zone = zone.covers(attempt.path)
    answers_as_read = attempt.operation in READ_OPERATIONS
    if aimed_at_zone and not answers_as_read:
        # The headline rejection, computed before the credential set
        # is consulted.  An operation the vocabulary cannot name is
        # not a read, and the zone answers nothing it cannot name —
        # so the unnamed spelling earns the same rejection as the
        # named ones, which is what makes "every write" total.
        operation = (
            repr(attempt.operation)
            if attempt.operation in WRITE_OPERATIONS
            else f"{attempt.operation!r}, not of the credential "
            f"vocabulary's read side"
        )
        return ZoneWriteDecision(
            allowed=False,
            reason=ZoneWriteReason.NO_WRITE_CREDENTIAL_FOR_IMMUTABLE_ZONE,
            detail=(
                f"write attempt from component {attempt.origin!r} to "
                f"{attempt.path!r} (operation {operation}) is rejected: "
                f"the place is inside the immutable zone "
                f"({zone.name!r}), and the component's credential set "
                f"holds no write capability for it. §2 fixes the line "
                f"absolutely — agents write to Z1 only, and Z1 has no "
                f"credential for Z0; enforce with filesystem "
                f"permissions, never with prompt instructions — and "
                f"§1 P1 keeps the zone one LLM-authored code has no "
                f"write credential for, so there is no spelling this "
                f"attempt could have used instead: not append, not the "
                f"trial ledger's own verb, whose appends are the "
                f"release process's to make; not chmod, which would be "
                f"reaching for the read-only mount itself (feature "
                f"148)."
            ),
        )

    credential = component.grant_for(attempt.path, attempt.operation)
    if credential is not None:
        permission = credential.grant_for(attempt.path, attempt.operation)
        return ZoneWriteDecision(
            allowed=True,
            reason=ZoneWriteReason.BY_PERMISSION,
            detail=(
                f"write attempt from component {attempt.origin!r} to "
                f"{attempt.path!r} (operation {attempt.operation!r}) is "
                f"allowed by credential {credential.name!r} of its "
                f"compiled set, whose permission on {permission.path!r} "
                f"answers {attempt.operation!r}. The place is outside "
                f"the immutable zone ({zone.name!r}) — the grant holds "
                f"real write capabilities for the component's own work "
                f"areas and nowhere else, which is exactly why its "
                f"emptiness on the zone is a law and not an accident "
                f"(feature 148)."
            ),
        )

    if aimed_at_zone:
        return ZoneWriteDecision(
            allowed=False,
            reason=ZoneWriteReason.NO_PERMISSION,
            detail=(
                f"attempt from component {attempt.origin!r} at "
                f"{attempt.path!r} (operation {attempt.operation!r}) is "
                f"rejected: the place is inside the immutable zone "
                f"({zone.name!r}) and no credential in the component's "
                f"set answers {attempt.operation!r} there. The zone is "
                f"read-only, not unreadable — a read-side operation "
                f"the set granted would be allowed — but this "
                f"component's set grants nothing on this member, so "
                f"the attempt holds no capability at all (feature "
                f"148)."
            ),
        )

    return ZoneWriteDecision(
        allowed=False,
        reason=ZoneWriteReason.NO_PERMISSION,
        detail=(
            f"write attempt from component {attempt.origin!r} to "
            f"{attempt.path!r} (operation {attempt.operation!r}) is "
            f"rejected: the place is outside the immutable zone "
            f"({zone.name!r}), and no credential in the component's "
            f"compiled set covers it. The set is real and finite — it "
            f"grants the work areas it grants — and an attempt outside "
            f"both the zone and the grant holds no capability at all "
            f"(feature 148)."
        ),
    )


def load_loop_credential_policy(path: Path) -> LoopCredentialPolicy:
    """Load and compile the loop credential grant at ``path``.

    JSON, read whole and compiled whole — the committed artifact
    (:data:`COMMITTED_LOOP_CREDENTIAL_POLICY`) and any proposed change
    to it pass through the same :func:`compile_loop_credential_policy`
    refusal, so the document on disk cannot drift open without the
    compile failing.
    """
    with path.open("r", encoding="utf-8") as handle:
        document = json.load(handle)
    return compile_loop_credential_policy(document)


def committed_loop_credential_policy() -> LoopCredentialPolicy:
    """The compiled credential grant of the loop's components as committed.

    The document this feature stands up: read from
    :data:`COMMITTED_LOOP_CREDENTIAL_POLICY` and compiled through the
    same law as any change to it, so what the gate consults and what
    the operator applied are provably the same grant.  This *is* the
    credential set of the feature's sentence — the one the system
    grants, whose every zone write is rejected before it is asked of
    anything.
    """
    return load_loop_credential_policy(COMMITTED_LOOP_CREDENTIAL_POLICY)
