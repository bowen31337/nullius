"""System rejects the merge when agent-writable paths overlap the immutable
zone.

app_spec.xml feature 353 — the first gate of the "System Invariant CI Gates"
category, and the merge-time form of the first stated invariant the whole
architecture leads with. docs/nullius-tech-architecture.md §1 opens its six
principles with P1 — *"The loop must not be able to weaken its own
validator."* — and states the consequence as a place and a posture: *"The
evaluator, cost model, and data snapshots live in a read-only trust zone
that LLM-authored code has no write credential for, and no network path
to."* spec_brief.yaml's constraints list carries the same law as its first
entry ("Must not modify the existing evaluator, cost model, or data
snapshots"), and §2's trust-zone table seats the posture in Z0's own row —
writable by *"Human, via signed release only"*, enforced by *"Read-only
mounts; separate IAM role; append-only ledger; CI hash check"*. That
enforcement column names this category: the CI gates are one of Z0's
instruments, and this one asks the question a merge gate can ask before
anything runs — **does this merge hand the agents a write capability that
reaches the immutable zone?**

**The two terms, stated exactly.**

* **An agent-writable path.** The agents are §2's Z1 writers — the row
  named *"Mutated by the loop"*, the signal agent and the
  policy-development agent writing through the two boxes §3's component
  map draws for that zone, the signal sandbox and the policy runtime.
  Where they may write is not prose: it is the committed credential grant
  (feature 148's artifact, ``infra/security/loop_credential_policy.json``)
  — the deployment's spelling of §2's *"enforce with filesystem
  permissions and network policy, never with prompt instructions"* — a
  credential set per component, each credential holding permissions, each
  permission one place and the operations it answers there. A path is
  agent-writable when some permission of some credential of some listed
  component carries a write-side operation on it, and the gate enumerates
  exactly those.

* **The immutable zone.** §2's Z0 contents — the data snapshots, the
  evaluator image, the cost model, the null oracle with its sidecar key,
  the trial ledger — pinned as rooted paths. Overlap is segment-wise and
  both directions are the law's: a writable path *inside* a member writes
  the zone's content, and a writable path *covering* one — the parent
  directory, ``/zones`` itself, the filesystem root — is *"a grant on the
  parent is a write to the zone in disguise"* (feature 148's own words
  for the same check), because a capability on the parent reaches every
  child. ``/zones/z0-sidecar`` is a neighbour, not a member, and a
  writable neighbour stands.

**Write is classified by the gate, not read from the grant's compiler.**
The runtime faces refuse the attempt (feature 147's mount raises before
any syscall) and the permission (feature 148's compile refuses the whole
document), and both faces ship in the merge too. A gate that judged the
grant by asking feature 148's compile whether it compiles would be
auditing with the very thing a weakening merge weakens first: delete the
compile's zone check and the same document compiles clean. So the gate
walks the parsed JSON itself and re-derives the classification. The read
side is restated here — ``read``, ``list``, ``stat``, the operations that
answer with the zone's content and leave it exactly as found — and **an
operation not of the read side is a write for this law**, the stance the
modules themselves hold ("an operation the vocabulary cannot name is not
a read"). No vocabulary edit can smuggle a verb past as a read: ``append``
reclassified onto the read side, or a fresh ``escalate`` the shipped
vocabulary has never heard of, each still counts as write intent here,
whatever the merge's enumeration says.

**The zone is pinned by two faces, and they must agree.** The grant
document carries its own ``immutable_zone`` block — the roots its compile
refuses writes against — and the mount module pins its own — the six
roots every service's read-only mount covers. The two features promise
one geometry in their own words ("the same roots feature 148's committed
grant pins, so the mount and the credential law protect exactly one
geometry"), and the gate holds that promise as data, three ways:

* the overlap judgement runs against **both faces' roots, unioned** — the
  mount's first, then any the document pins that the mount does not — so
  a write overlapping either face's zone is an overlap with the immutable
  zone, whichever face a merge tried to move;
* a document that names no zone is a finding, not a default — the
  compile's own :class:`~infra.security.loop_credentials.
  MissingImmutableZone` refusal restated at merge time, because a grant
  that cannot say which paths are the zone could never recognize the
  write it must refuse;
* the two faces' pin sets must agree, and each must still cover the law's
  own members — P1's three (the data snapshots, the evaluator, the cost
  model: the first stated invariant's own subjects), §2's Z0 row
  completing the zone (the null oracle, the trial ledger), the layout's
  contract. Narrowing a face is refused; widening one stands — the
  polarity of every tightening in this tree
  (:func:`~infra.security.zone_mount.materialize_read_only` can only
  clear bits, never set them).

**Reads are served, and Z1/Z3 writes stand — the stands cases are
load-bearing.** §2's Z0 is read-only, not unreadable, and the committed
grant says so in capability form: the policy runtime holds read-only
credentials on two zone members (§5: *"Feature definitions live in Z0 and
are versioned"*), and those grants are not findings. The agents' writable
paths are real — their own Z1 work areas and the Z3 artifact drop where
proposed code lands — because *"a set that can truly write somewhere and
still cannot write the zone anywhere in its set is the feature's own
shape"* (the artifact's own comment): a gate that passed an empty grant
would pass a stupider system, refusing nothing because it grants nothing.

**Why CI, and why the harm is silent.** P1's name is the harm: the loop
weakening its own validator. A write capability onto the zone is the
one-commit path from the searched code to its own grader — the evaluator
it is scored by, the cost model its scores pay through, the snapshots its
signals are drawn from, the ledger whose charges bound its budget.
Nothing in the loop would catch the use: the runtime mount refuses the
write, but the loop's honesty should not have to depend on the mount
being the last line, and §2's enforcement column lists the CI beside the
mount precisely because the grant that would defeat it ships in a merge.
Refused at merge time, the overlap costs a red gate; landed, it costs the
one property every calibration number downstream stands on.

**What this gate is not, asserted as hard as what it is.** It is not
feature 147's mount — that refuses the *attempt* at answer time with a
permission error; this refuses the *grant* before anything runs. It is
not feature 148's compile or its answer-time gate — those are the
member-side faces of the same law, and a merge that weakened them is
caught here because this gate re-derives, from the raw document, what
they would have checked. It is not an audit of where else the agents
write: a write capability on a path outside the zone — a scratch
directory, a tmpdir — is §2's "agents write to Z1 only" and feature 148's
scope, not this sentence's; the gate refuses the overlap, exactly. It is
not the member suites — those pin the law from inside; this reads what a
merge carries, from outside it, and adds the face no member-side test can
promise: a grant that reaches the zone refuses the merge whatever else it
does.

**Honest limits.** The gate walks the grant's canonical shape —
components, credentials and permissions as mappings, a path and an
operations list each — and blocks the compile refuses outright (a
malformed operations list, a non-string name) are the member suite's
refusals, not silently-standing merges. Where a *place* cannot be pinned
— a relative path, "wherever a hostile reader's working directory left
it", or the ``//`` prefix POSIX leaves implementation-defined — the gate
fails closed: a capability whose place cannot be named cannot be shown to
miss the zone, and is refused as unpinnable. And the mount module is
trusted for its own geometry: a merge that moved the zone roots and the
grant's block together, consistently and still covering the six members,
has redeployed the zone rather than overlapped it — the member checks are
what keep that move honest. Stdlib and the mount module only; the
evaluators are pure functions of a parsed document and a tuple of roots,
pinned statically below, because a gate that had to compile the grant to
judge it would be an audit after the weakening.
"""

from __future__ import annotations

import ast
import copy
import inspect
import json
import posixpath
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

# The gate judges a second artifact beside the grant: the mount module's
# committed zone geometry, the other enforcement face. ``infra/`` is
# deliberately outside the uv workspace's import graph (policy that guards
# the zones must not be composition code — see ``infra/security/__init__.
# py``), so this module bootstraps the repository root onto ``sys.path``
# the way infra's own suites do (``infra/security/tests/loop_credentials/
# conftest.py``): ``infra`` resolves as the PEP 420 namespace package it
# is, with no ``infra/__init__.py`` and none to be created.
REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from infra.security import zone_mount  # noqa: E402

# ── The law's own spellings, restated as data ────────────────────────────────

#: The committed credential grant of the loop-mutated components — the
#: artifact whose write capabilities this gate judges, read by path so the
#: gate grades the file the merge ships, not a restatement typed here. The
#: path is built from the repository root the way feature 361's gate builds
#: its migration's, and for the same reason: the one failure a gate should
#: never have to guess at is "the artifact moved" — a gate that silently
#: skipped the grant would pass for a merge that shipped anything.
COMMITTED_GRANT = REPO_ROOT / "infra" / "security" / "loop_credential_policy.json"

if not COMMITTED_GRANT.is_file():
    raise AssertionError(
        f"the committed loop credential grant is not at {COMMITTED_GRANT}; "
        "this gate judges the agent-writable paths the merge declares, so "
        "it needs the grant to be where the tree keeps it"
    )

#: The grant as the merge ships it, parsed once at collection — reading it
#: is a precondition of every judgement below, not a behaviour any one test
#: chooses. Never compiled: the evaluators walk this mapping as data (see
#: the module docstring for why asking feature 148's compile would be
#: auditing with the thing a weakening merge weakens first).
COMMITTED_DOCUMENT: object = json.loads(COMMITTED_GRANT.read_text(encoding="utf-8"))

#: The immutable zone's roots as the mount pins them — the other face.
#: Read from the module the merge ships rather than restated here, so the
#: gate and the runtime mount cannot disagree about where the zone is; the
#: member checks below hold that geometry to the law's own enumeration.
MOUNT_ZONE_PATHS: tuple[str, ...] = zone_mount.ZONE_PATHS

#: The read side of the operation vocabulary, restated as this gate's own
#: classification — the operations that answer with the zone's content and
#: leave it exactly as found. Everything else is write intent for this law
#: (the modules' own stance: "an operation the vocabulary cannot name is
#: not a read"), so no vocabulary edit in the shipped compiler can smuggle
#: a verb past as a read here.
READ_OPERATIONS: frozenset[str] = frozenset({"read", "list", "stat"})

#: The write side the law enumerates — the eight verbs the credential
#: vocabulary spells, held here as documentation of the classification's
#: reach rather than as the classifier itself: each of these is refused
#: onto the zone by name in the parameterised case below, and any verb
#: outside :data:`READ_OPERATIONS` is refused whether enumerated or not.
WRITE_OPERATIONS: frozenset[str] = frozenset(
    {
        "write",
        "append",
        "create",
        "delete",
        "rename",
        "truncate",
        "chmod",
        "chown",
    }
)

#: The immutable zone's member roots by name — the law's own enumeration of
#: §2's Z0 contents. P1's arrow names the first three (the data snapshots,
#: the evaluator, the cost model — the first stated invariant's own
#: subjects); §2's Z0 row adds the null oracle and the trial ledger; the
#: repository layout adds the contract. Held by final path segment, not by
#: full literal, because the mount point is deployment spelling ("Paths
#: are examples for the zone's shape", the artifact's own comment) while
#: the contents are law: a redeployment may move the prefix, never a
#: member.
ZONE_MEMBERS: tuple[str, ...] = (
    "snapshots",
    "evaluator",
    "cost-model",
    "contract",
    "nulloracle",
    "trial-ledger",
)


# ── The evaluators: pure functions of a document and a tuple of roots ────────


@dataclass(frozen=True)
class ZoneOverlap:
    """One agent-writable path that reaches the immutable zone.

    The operator-facing form of the refusal: which component's credential
    carries the capability, the path as the document spelled it, the
    write-intent operations it carries, the direction of the reach, and
    the zone member it touches — so the drift is findable in the file it
    was written in, the way feature 361's refusal names the role beside
    the verb it holds.
    """

    #: The loop-mutated component whose credential set carries the
    #: capability, as the document names it.
    component: str
    #: The named credential holding the offending permission.
    credential: str
    #: The permission's path, exactly as the document spells it.
    path: str
    #: The write-intent operations the permission carries, sorted.
    operations: tuple[str, ...]
    #: ``inside`` (the path is at or under a zone member), ``covering``
    #: (the path is an ancestor of one — a grant on the parent), or
    #: ``unpinnable`` (the path names no place that can be compared).
    direction: str
    #: The zone member root the reach touches, or ``""`` when unpinnable.
    member: str


@dataclass(frozen=True)
class GeometryDrift:
    """One way the two faces' zone geometry no longer says what the law
    says.

    ``face`` is which artifact pins (or fails to pin) the subject — the
    grant document or the mount module — and ``subject`` is the path that
    disagrees between the faces, the absent zone block, or the member a
    face no longer covers. ``detail`` carries the operator-facing
    sentence.
    """

    face: str
    subject: str
    detail: str


def _canonical_place(path: object) -> str | None:
    """Return ``path`` as a canonical absolute POSIX path, or ``None``.

    Absolute, because a relative place is wherever a hostile reader's
    working directory left it — "a permission that moves with the reader
    is not a permission, it is an accident" (the grant's own compiler).
    Normalized, so ``..`` and ``.`` and a trailing slash collapse before
    the path is trusted. A path that will not canonicalize — the POSIX
    ``//`` prefix the normalization preserves — resolves nowhere either
    face pinned, so it is ``None``: a place the gate cannot pin is a
    place the gate cannot show to miss the zone.
    """
    if not isinstance(path, str) or not path.startswith("/"):
        return None
    normalized = posixpath.normpath(path)
    if normalized.startswith("//"):
        return None
    return normalized


def _at_or_under(outer: str, inner: str) -> bool:
    """Whether canonical absolute ``inner`` is ``outer`` or lies under it.

    Segment-wise, so ``/zones/z0-sidecar`` is a neighbour, not a child of
    ``/zones/z0`` — and the filesystem root is handled for what it is, the
    one prefix whose separator-appended form (``//``) matches nothing.
    Restated here rather than imported, so the gate's containment and the
    modules' cannot be weakened in the same edit.
    """
    if inner == outer:
        return True
    if outer == "/":
        return inner.startswith("/")
    return inner.startswith(outer + "/")


def _write_operations(raw: object) -> tuple[str, ...]:
    """The write-intent operations of a permission's operations list.

    Every operation not of the restated read side counts as write intent,
    well-formed and hostile alike — the classifier is the gate's own, so
    the shipped vocabulary's spelling of "write" cannot narrow it. Shapes
    the compile would refuse outright (a non-list, an empty list, non-string
    entries) contribute nothing: they are not capabilities a standing
    merge could hold.
    """
    if not isinstance(raw, list):
        return ()
    return tuple(
        sorted(
            {
                operation
                for operation in raw
                if isinstance(operation, str) and operation not in READ_OPERATIONS
            }
        )
    )


def agent_writable_paths(
    document: object,
) -> tuple[tuple[str, str, object, tuple[str, ...]], ...]:
    """Every (component, credential, path, operations) the grant makes
    writable.

    The inspectable form of the subject: a walk of the parsed document's
    canonical shape — components, credentials, permissions — collecting
    each permission whose operations carry write intent, in document
    order, with the path exactly as the document spells it, whatever it
    spelled — the judgement below canonicalizes, and refuses what it
    cannot. Read-side permissions are deliberately absent (the zone is
    readable, and a read grant on a member is not a finding); blocks the
    walk cannot read are
    the compile's refusals, and contribute nothing here.
    """
    if not isinstance(document, dict):
        return ()
    findings: list[tuple[str, str, str, tuple[str, ...]]] = []
    components = document.get("components")
    if not isinstance(components, list):
        return ()
    for block in components:
        if not isinstance(block, dict) or not isinstance(block.get("name"), str):
            continue
        credentials = block.get("credentials")
        if not isinstance(credentials, list):
            continue
        for credential in credentials:
            if not isinstance(credential, dict) or not isinstance(
                credential.get("name"), str
            ):
                continue
            permissions = credential.get("permissions")
            if not isinstance(permissions, list):
                continue
            for permission in permissions:
                if not isinstance(permission, dict):
                    continue
                operations = _write_operations(permission.get("operations"))
                if not operations:
                    continue
                findings.append(
                    (block["name"], credential["name"], permission.get("path"), operations)
                )
    return tuple(findings)


def overlap_findings(
    document: object, zone_roots: object
) -> tuple[ZoneOverlap, ...]:
    """Every agent-writable path in ``document`` that reaches the zone.

    The gate itself, parameterised by the zone's roots so a judgement can
    be run against either enforcement face's geometry (see
    :func:`pinned_zone_roots`, which unions them). Both directions are the
    law's: *inside* writes the zone's content, *covering* writes the zone
    in disguise, and a path that cannot be pinned at all is refused as
    ``unpinnable`` — fail closed, because a capability whose place cannot
    be named cannot be shown to miss the zone.
    """
    if not isinstance(zone_roots, (list, tuple)):
        zone_roots = ()
    roots = tuple(zone_roots)
    findings: list[ZoneOverlap] = []
    for component, credential, raw_path, operations in agent_writable_paths(document):
        spelled = raw_path if isinstance(raw_path, str) else repr(raw_path)
        place = _canonical_place(raw_path)
        if place is None:
            findings.append(
                ZoneOverlap(
                    component=component,
                    credential=credential,
                    path=spelled,
                    operations=operations,
                    direction="unpinnable",
                    member="",
                )
            )
            continue
        member = next(
            (root for root in roots if _at_or_under(root, place)), None
        )
        if member is not None:
            findings.append(
                ZoneOverlap(
                    component=component,
                    credential=credential,
                    path=spelled,
                    operations=operations,
                    direction="inside",
                    member=member,
                )
            )
            continue
        covering = next(
            (root for root in roots if _at_or_under(place, root)), None
        )
        if covering is not None:
            findings.append(
                ZoneOverlap(
                    component=component,
                    credential=credential,
                    path=spelled,
                    operations=operations,
                    direction="covering",
                    member=covering,
                )
            )
    return tuple(findings)


def _document_zone_block(document: object) -> tuple[bool, tuple[str, ...]]:
    """The document's zone block as ``(readable, canonical paths)``.

    All-or-nothing, the compiler's own stance: a block that is absent, or
    not a mapping, or whose paths are not a non-empty list, or any of
    whose entries will not canonicalize, is unreadable as a whole — a
    grant that cannot say which paths are the zone could never recognize
    the write it must refuse, and the geometry finding below says so
    rather than letting a half-read block stand for the zone.
    """
    if not isinstance(document, dict):
        return (False, ())
    block = document.get("immutable_zone")
    if not isinstance(block, dict):
        return (False, ())
    raw_paths = block.get("paths")
    if not isinstance(raw_paths, list) or not raw_paths:
        return (False, ())
    canonical: list[str] = []
    for entry in raw_paths:
        path = _canonical_place(entry)
        if path is None:
            return (False, ())
        canonical.append(path)
    return (True, tuple(canonical))


def pinned_zone_roots(
    document: object, mount_roots: object = None
) -> tuple[str, ...]:
    """The immutable zone's roots as both enforcement faces pin them.

    The mount's committed geometry first, then any root the document's own
    block pins that the mount does not — unioned, so a write overlapping
    either face's zone is an overlap with the immutable zone: a merge that
    shrank one face's geometry to hide a write behind the other's blind
    spot still meets the union, and the geometry findings below name the
    disagreement besides. ``mount_roots`` defaults to the committed mount
    and may be supplied explicitly so a judgement can be run against a
    candidate mount's geometry — the shrunk-mount case below holds the
    union's promise from the other side.
    """
    pinned = MOUNT_ZONE_PATHS if mount_roots is None else tuple(mount_roots)
    _, document_paths = _document_zone_block(document)
    roots = list(pinned)
    for path in document_paths:
        if path not in roots:
            roots.append(path)
    return tuple(roots)


def geometry_findings(
    document: object, mount_roots: object
) -> tuple[GeometryDrift, ...]:
    """Every way the two faces' geometry no longer says what the law says.

    Three findings, in a fixed order: a document whose zone block cannot
    be read (absent, malformed, or carrying an uncanonicalizable root);
    each root the faces disagree over — named with the face that pins it,
    so the operator sees where the place is still protected; and each law
    member a face no longer covers, the narrowing that would take a
    subject out of the invariant. Widening is deliberately not a finding:
    adding a member tightens the zone, and tightening is never refused.
    """
    if not isinstance(mount_roots, (list, tuple)):
        mount_roots = ()
    pinned = tuple(mount_roots)
    findings: list[GeometryDrift] = []

    readable, document_paths = _document_zone_block(document)
    if not readable:
        findings.append(
            GeometryDrift(
                face="grant",
                subject="immutable_zone",
                detail=(
                    "the grant names no immutable zone readable as a "
                    "whole. The feature's law is named for the place it "
                    "protects, and a grant that cannot say which paths are "
                    "the zone could never recognize the write it must "
                    "refuse — the compile's own refusal, restated at merge "
                    "time (feature 353 over feature 148)."
                ),
            )
        )
        document_paths = ()

    for path in sorted(set(document_paths) ^ set(pinned)):
        face = "grant" if path in document_paths else "mount"
        holder = "the grant" if face == "grant" else "the mount"
        other = "the mount" if face == "grant" else "the grant"
        findings.append(
            GeometryDrift(
                face=face,
                subject=path,
                detail=(
                    f"{path} is pinned by {holder} but not {other} — the "
                    f"mount and the credential law are promised one "
                    f"geometry, and a root only one of them protects is a "
                    f"boundary the two enforcement faces enforce "
                    f"differently (feature 353)."
                ),
            )
        )

    for face, paths in (("grant", document_paths), ("mount", pinned)):
        members = {path.rsplit("/", 1)[-1] for path in paths}
        for member in ZONE_MEMBERS:
            if member in members:
                continue
            findings.append(
                GeometryDrift(
                    face=face,
                    subject=f"member {member}",
                    detail=(
                        f"the {face} face's zone geometry no longer names "
                        f"a member root for {member}. §2's Z0 row and P1's "
                        f"own arrow enumerate the zone's contents, and a "
                        f"geometry that drops one has taken that subject "
                        f"out of the invariant's protection — narrowing "
                        f"refused, widening never (feature 353)."
                    ),
                )
            )
    return tuple(findings)


def merge_refusal(document: object) -> tuple[ZoneOverlap, ...]:
    """The gate's own headline: agent-writable paths that reach the zone.

    The merge-time form of P1. Empty means no capability the grant grants
    reaches the immutable zone, in either direction, under either face's
    geometry — the merge stands on this sentence. Computed from the
    document as data, never by compiling it.
    """
    return overlap_findings(document, pinned_zone_roots(document))


def geometry_refusal(document: object) -> tuple[GeometryDrift, ...]:
    """The belt behind the headline: the zone both faces say is the zone.

    Judged against the mount module's committed geometry — the face this
    gate imports, not one the document controls. Empty means the grant and
    the mount still pin one geometry that still covers the law's own
    members.
    """
    return geometry_findings(document, MOUNT_ZONE_PATHS)


# ── The committed document, varied the way a candidate merge would ──────────


def _grant_document() -> dict:
    """A writable copy of the committed grant, for a candidate merge's
    shape: every helper below starts from what ships and changes exactly
    one thing, the way the drift actually arrives — an edit, not a
    rewrite."""
    return copy.deepcopy(COMMITTED_DOCUMENT)


def _with_extra_permission(
    component: str, credential: str, path: str, operations: list[str]
) -> dict:
    """The committed grant plus one permission on an existing credential.

    The quiet drift's own shape: the component and role the deployment
    already grants, asked to answer one more capability at one more place.
    """
    document = _grant_document()
    for block in document["components"]:
        if block["name"] != component:
            continue
        for granted in block["credentials"]:
            if granted["name"] != credential:
                continue
            granted["permissions"].append(
                {"path": path, "operations": operations}
            )
            return document
    raise AssertionError(
        f"the committed grant names no credential {credential!r} on "
        f"component {component!r}; the fixture asked for a shape the "
        "artifact does not carry"
    )


def _with_extra_component(name: str, path: str, operations: list[str]) -> dict:
    """The committed grant plus a whole component holding one write.

    The identity probe: a component the committed grant never mentions,
    granted a capability at the zone — the gate is on the capability, not
    on the name, and a foreign box is refused all the same.
    """
    document = _grant_document()
    document["components"].append(
        {
            "name": name,
            "credentials": [
                {
                    "name": f"{name}-role",
                    "permissions": [{"path": path, "operations": operations}],
                }
            ],
        }
    )
    return document


def _with_zone_paths(paths: tuple[str, ...]) -> dict:
    """The committed grant with its zone block re-pinned to ``paths``.

    The narrowing probe: everything else about the grant untouched, the
    geometry moved — the merge that would hide a write behind a zone that
    shrank to miss it.
    """
    document = _grant_document()
    document["immutable_zone"] = {"name": "z0-immutable", "paths": list(paths)}
    return document


def _with_zone_write(path: str) -> dict:
    """The committed grant plus one write onto a zone member.

    The load-bearing regression case's subject: a change to the artifact
    that grants a loop-mutated component a write at the zone — typo,
    "temporary" backfill, a copy-paste from a work-area permission — which
    must fail this gate at merge time, before any service consults the
    grant.
    """
    return _with_extra_permission(
        "policy-runtime", "policy-runtime-role", path, ["append"]
    )


#: The committed grant's two loop-mutated components — §3's Z1 boxes, the
#: signal sandbox and the policy runtime, the same membership feature
#: 148's and 149's committed documents hold.
LOOP_MUTATED_COMPONENTS: frozenset[str] = frozenset({"signal-sandbox", "policy-runtime"})


# ── The gate reads the grant the merge carries ───────────────────────────────


class TestTheGateReadsTheGrantTheMergeCarries:
    """The gate judges the grant the merge ships, as data, without
    compiling it — and the zone it judges against is pinned by a second
    face the document does not control."""

    def test_the_gate_reads_the_committed_grant_by_path(self) -> None:
        # The gate reads the artifact itself — the file a candidate merge
        # would edit, parsed as JSON — never a restatement typed into this
        # file. A gate that re-typed the grant it judged could agree with
        # itself and pass anything; this one fails the moment the artifact
        # moves or changes shape. And the document declares what it is:
        # the compiler's own marker, so a stray JSON file carrying a
        # ``components`` key is not read as the loop's grant.
        assert isinstance(COMMITTED_DOCUMENT, dict)
        assert COMMITTED_DOCUMENT["policy"] == "loop-credentials"

    def test_the_grant_carries_both_components_and_real_writes(self) -> None:
        # The subject is non-empty, and named: §2's Z1 writers are the two
        # boxes §3 draws (the signal sandbox, the policy runtime), and the
        # committed grant holds write-capable permissions for both. If the
        # artifact ever stopped carrying real write capabilities, this
        # fails before the gate can silently judge an empty subject — the
        # stands case is not "the agents may write nothing".
        writable = agent_writable_paths(COMMITTED_DOCUMENT)
        assert writable, "the committed grant must hold real write capabilities"
        assert {entry[0] for entry in writable} == LOOP_MUTATED_COMPONENTS

    def test_the_gate_judges_the_document_without_compiling_it(self) -> None:
        # A merge gate refuses the change before it ships; an evaluator
        # that had to ask feature 148's compile — or open the artifact, or
        # consult the answer-time gate — to judge the document would be
        # auditing with the very seams a weakening merge weakens first.
        # Pinned statically, the way feature 361's gate pins its evaluator
        # off the database: the evaluators' own source touches nothing
        # that compiles, loads or answers the grant.
        sources = "".join(
            inspect.getsource(evaluator)
            for evaluator in (
                agent_writable_paths,
                overlap_findings,
                pinned_zone_roots,
                geometry_findings,
                merge_refusal,
                geometry_refusal,
            )
        )
        tree = ast.parse(sources)
        touched = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
        touched |= {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
        assert not touched & {
            "compile_loop_credential_policy",
            "load_loop_credential_policy",
            "committed_loop_credential_policy",
            "authorize_zone_write",
            "authorize_zone_access",
            "open",
            "read_text",
        }

    def test_both_enforcement_faces_pin_one_geometry(self) -> None:
        # The grant's own zone block and the mount module's committed
        # geometry are promised to be one ("the same roots feature 148's
        # committed grant pins, so the mount and the credential law
        # protect exactly one geometry") — and the gate holds that promise
        # as data rather than trusting either face alone. The committed
        # document produces no geometry findings against the mount's
        # roots.
        assert geometry_refusal(COMMITTED_DOCUMENT) == ()
        _, document_paths = _document_zone_block(COMMITTED_DOCUMENT)
        assert frozenset(document_paths) == frozenset(MOUNT_ZONE_PATHS)

    def test_the_zone_still_names_the_laws_own_members(self) -> None:
        # P1's arrow names the data snapshots, the evaluator and the cost
        # model — the first stated invariant's own subjects; §2's Z0 row
        # completes the zone with the null oracle and the trial ledger;
        # the layout adds the contract. Both faces' roots are held to that
        # enumeration by final segment (the mount point is deployment
        # spelling; the contents are law), so a merge that drops a member
        # from either geometry is a merge that took a subject out of the
        # invariant's protection.
        for face, paths in (
            ("mount", MOUNT_ZONE_PATHS),
            ("grant", _document_zone_block(COMMITTED_DOCUMENT)[1]),
        ):
            assert {path.rsplit("/", 1)[-1] for path in paths} == set(ZONE_MEMBERS), face


# ── A merge whose writable paths miss the zone stands ─────────────────────────


class TestAMergeWhoseWritablePathsMissTheZoneStands:
    """The committed grant is the stands case: the agents write somewhere,
    the zone serves reads, and neither reaches the other."""

    def test_the_committed_grant_stands(self) -> None:
        # The gate's own happy path, stated as the gate states it: no
        # capability the system grants reaches the immutable zone, in
        # either direction, under either face's geometry — and the two
        # faces still say the zone is the same place the law does.
        assert merge_refusal(COMMITTED_DOCUMENT) == ()
        assert geometry_refusal(COMMITTED_DOCUMENT) == ()

    def test_the_agents_writable_paths_live_in_z1_and_z3(self) -> None:
        # The stands case is not "no grants at all". The grant's write
        # capabilities are exactly the committed four — each component's
        # own Z1 work area and the Z3 artifact drop where proposed code
        # lands — which is §2's "agents write to Z1 only" made auditable:
        # a gate that passed an empty grant would pass a stupider system,
        # refusing nothing because it grants nothing.
        writable = sorted({entry[2] for entry in agent_writable_paths(COMMITTED_DOCUMENT)})
        assert writable == [
            "/zones/z1/policy-runtime/work",
            "/zones/z1/signal-sandbox/work",
            "/zones/z3/artifacts/policy",
            "/zones/z3/artifacts/signal",
        ]

    def test_the_zones_read_grants_are_not_writings(self) -> None:
        # §2's Z0 is read-only, not unreadable, and the committed grant
        # says so in capability form: the policy runtime holds read-only
        # credentials on two zone members (§5: feature definitions live in
        # Z0 and are versioned). Those permissions carry no write intent
        # under the gate's own classification, so they are not findings —
        # the barrier's edge is between reading the zone and writing it,
        # and only the second refuses the merge.
        document = COMMITTED_DOCUMENT
        assert isinstance(document, dict)
        zone_reads = [
            permission
            for block in document["components"]
            if block["name"] == "policy-runtime"
            for granted in block["credentials"]
            for permission in granted["permissions"]
            if isinstance(permission["path"], str)
            and permission["path"].startswith("/zones/z0/")
        ]
        assert zone_reads, "the committed grant must hold the policy runtime's zone reads"
        for permission in zone_reads:
            assert set(permission["operations"]) <= READ_OPERATIONS
            assert _write_operations(permission["operations"]) == ()
        # And none of them was counted among the writable paths.
        assert all(
            not entry[2].startswith("/zones/z0/")
            for entry in agent_writable_paths(document)
        )

    def test_a_neighbour_of_the_zone_is_not_the_zone(self) -> None:
        # Containment is segment-wise: ``/zones/z0-sidecar`` shares the
        # zone's prefix but not its boundary, and a write capability there
        # is a capability somewhere else — refused by nothing this gate
        # says. The same discipline the mount's containment holds by, read
        # from the refusal side so a prefix-shaped dodge cannot work.
        document = _with_extra_permission(
            "signal-sandbox",
            "signal-sandbox-role",
            "/zones/z0-sidecar",
            ["create", "write"],
        )
        assert merge_refusal(document) == ()

    def test_widening_the_zone_in_step_stands(self) -> None:
        # Narrowing is refused; widening is tightening, and tightening is
        # never refused. A geometry that adds a seventh member root — to
        # both faces, consistently, since the two are promised one —
        # produces no drift finding and refuses nothing, the same
        # polarity :func:`zone_mount.materialize_read_only` holds: clearing
        # bits cannot add one.
        widened = (*MOUNT_ZONE_PATHS, "/zones/z0/feature-store")
        document = _with_zone_paths(widened)
        assert geometry_findings(document, widened) == ()
        assert merge_refusal(document) == ()


# ── A merge whose writable paths overlap the zone is refused ──────────────────


class TestAMergeWhoseWritablePathsOverlapTheZoneIsRefused:
    """Any component, any verb, any spelling, either direction — the
    overlap refuses the merge, and the refusal names who holds what."""

    def test_one_append_onto_the_trial_ledger_refuses_the_merge(self) -> None:
        # The quiet drift: the committed grant plus one permission on the
        # role the deployment already grants — the ledger's own verb,
        # whose appends are the release process's to make. The single
        # finding names the component, the path as spelled, the operation,
        # the direction and the member, so the operator reads the break
        # off the artifact rather than re-deriving it.
        (finding,) = merge_refusal(_with_zone_write("/zones/z0/trial-ledger"))
        assert finding.component == "policy-runtime"
        assert finding.credential == "policy-runtime-role"
        assert finding.path == "/zones/z0/trial-ledger"
        assert finding.operations == ("append",)
        assert finding.direction == "inside"
        assert finding.member == "/zones/z0/trial-ledger"

    @pytest.mark.parametrize("operation", sorted(WRITE_OPERATIONS))
    def test_every_write_verb_onto_a_zone_member_is_refused(
        self, operation: str
    ) -> None:
        # "Every write" enumerates something, or a spelling nobody listed
        # could slip past as neither read nor write. Each of the eight
        # verbs the credential vocabulary spells — including ``append``
        # the ledger lives on and ``chmod``, which would be reaching for
        # the read-only mount itself — refuses the merge onto a zone
        # member, P1's own subject (the cost model).
        document = _with_extra_permission(
            "policy-runtime",
            "policy-runtime-role",
            "/zones/z0/cost-model",
            [operation],
        )
        (finding,) = merge_refusal(document)
        assert finding.direction == "inside"
        assert finding.member == "/zones/z0/cost-model"
        assert finding.operations == (operation,)

    @pytest.mark.parametrize("path", ["/zones/z0", "/zones", "/"])
    def test_a_grant_on_the_parent_covers_the_zone(self, path: str) -> None:
        # A capability on the parent reaches every child — "a grant on the
        # parent is a write to the zone in disguise", feature 148's own
        # words for the covering direction. The filesystem root is the
        # loudest form: a write capability on ``/`` is a write capability
        # on everything, the zone included.
        document = _with_extra_permission(
            "signal-sandbox", "signal-sandbox-role", path, ["write"]
        )
        (finding,) = merge_refusal(document)
        assert finding.direction == "covering"
        assert finding.member in MOUNT_ZONE_PATHS

    def test_a_deep_path_inside_a_member_is_refused(self) -> None:
        # The reach is not only at the member root: a write capability on
        # a file deep inside the evaluator is a write capability on the
        # evaluator, and the refusal names the member it lives under —
        # the drift is findable however far down it is spelled.
        document = _with_extra_permission(
            "signal-sandbox",
            "signal-sandbox-role",
            "/zones/z0/evaluator/pipeline.py",
            ["write"],
        )
        (finding,) = merge_refusal(document)
        assert finding.direction == "inside"
        assert finding.member == "/zones/z0/evaluator"

    @pytest.mark.parametrize(
        "path",
        ["/zones/z0/../z0/contract", "/zones/z0/contract/"],
    )
    def test_traversal_and_trailing_slash_spellings_collapse(self, path: str) -> None:
        # Containment is decided on where the path resolves, not on how it
        # was typed: a traversal-shaped walk through the zone's own parent
        # and a trailing slash are the contract member, and the refusal
        # says so — the same normalization the mount and the grant's
        # compiler pin their geometries with.
        document = _with_extra_permission(
            "policy-runtime", "policy-runtime-role", path, ["truncate"]
        )
        (finding,) = merge_refusal(document)
        assert finding.path == path
        assert finding.direction == "inside"
        assert finding.member == "/zones/z0/contract"

    def test_a_foreign_component_and_a_foreign_credential_are_the_same_finding(
        self,
    ) -> None:
        # The gate is on the capability, not the identity. A component the
        # committed grant never mentions — and a second credential on one
        # it does — is refused exactly as the quiet drift is: a name check
        # would have to enumerate the boxes it distrusts, and the sentence
        # refuses the reach, however the holder is called.
        foreign = _with_extra_component(
            "discovery-orchestrator", "/zones/z0/snapshots", ["write"]
        )
        (finding,) = merge_refusal(foreign)
        assert finding.component == "discovery-orchestrator"
        assert finding.member == "/zones/z0/snapshots"

        document = _grant_document()
        document["components"][0]["credentials"].append(
            {
                "name": "signal-sandbox-scratch",
                "permissions": [
                    {"path": "/zones/z0/nulloracle", "operations": ["create"]}
                ],
            }
        )
        (finding,) = merge_refusal(document)
        assert finding.credential == "signal-sandbox-scratch"
        assert finding.member == "/zones/z0/nulloracle"

    def test_an_operation_the_read_side_cannot_name_is_a_write(self) -> None:
        # The classification is the gate's own, restated: an operation not
        # of the read side is write intent, whether the shipped vocabulary
        # has heard of it or not. A merge that reclassified ``append`` onto
        # the read side, or coined a verb for the occasion, cannot smuggle
        # the capability past as a reading — "an unnamed verb is not a
        # read", the modules' own stance, held here as data.
        document = _with_extra_permission(
            "policy-runtime",
            "policy-runtime-role",
            "/zones/z0/cost-model",
            ["read", "escalate"],
        )
        (finding,) = merge_refusal(document)
        assert finding.operations == ("escalate",)
        assert finding.direction == "inside"

    @pytest.mark.parametrize("path", ["z0/contract", "//zones/z0/contract"])
    def test_a_permission_whose_place_cannot_be_pinned_is_refused(
        self, path: str
    ) -> None:
        # Fail closed on the placeless: a relative path is wherever a
        # hostile reader's working directory left it, and the ``//`` prefix
        # is the one POSIX leaves implementation-defined — neither can be
        # shown to miss the zone, so neither stands. A gate that treated
        # an uncomparable place as outside would be granting the benefit
        # of the doubt to exactly the shapes that exist to collect it.
        document = _with_extra_permission(
            "signal-sandbox", "signal-sandbox-role", path, ["write"]
        )
        (finding,) = merge_refusal(document)
        assert finding.direction == "unpinnable"
        assert finding.member == ""

    def test_a_merge_that_shrinks_the_grants_zone_is_caught_by_the_mounts(
        self,
    ) -> None:
        # The union is the point: a merge that re-pins the document's zone
        # block to exclude the member it then writes onto has not moved
        # the immutable zone, only the document's claim about it — the
        # mount still pins the member, so the overlap finding stands, and
        # the geometry findings name the disagreement besides. Hiding a
        # write behind a shrunken block costs two findings, not zero.
        narrowed = tuple(
            path for path in MOUNT_ZONE_PATHS if path != "/zones/z0/cost-model"
        )
        document = _with_zone_paths(narrowed)
        for block in document["components"]:
            if block["name"] == "policy-runtime":
                for granted in block["credentials"]:
                    if granted["name"] == "policy-runtime-role":
                        granted["permissions"].append(
                            {
                                "path": "/zones/z0/cost-model",
                                "operations": ["write"],
                            }
                        )
        (finding,) = merge_refusal(document)
        assert finding.direction == "inside"
        assert finding.member == "/zones/z0/cost-model"
        subjects = {drift.subject for drift in geometry_refusal(document)}
        assert "/zones/z0/cost-model" in subjects
        assert "member cost-model" in subjects

    def test_a_merge_that_shrinks_the_mount_geometry_is_caught_by_the_grant(
        self,
    ) -> None:
        # The mirror: a merge that narrowed the mount module's own
        # geometry (the face this gate imports) cannot hide a grant-side
        # write behind it, because the document's own block still pins the
        # member and the judgement runs against both. Judged here as a
        # pure evaluation over a synthetic shrunk mount, since the
        # committed module's geometry is not a test's to mutate.
        shrunk = tuple(
            path for path in MOUNT_ZONE_PATHS if path != "/zones/z0/evaluator"
        )
        document = _with_zone_write("/zones/z0/evaluator")
        findings = overlap_findings(document, pinned_zone_roots(document, shrunk))
        assert any(
            finding.member == "/zones/z0/evaluator" for finding in findings
        )
        # And the drift itself is named: the faces disagree, and the mount
        # no longer covers a law member.
        subjects = {
            drift.subject for drift in geometry_findings(document, shrunk)
        }
        assert "/zones/z0/evaluator" in subjects
        assert "member evaluator" in subjects


# ── The refusal is scoped to the overlap and nothing else ─────────────────────


class TestTheRefusalIsScopedToTheOverlapAndNothingElse:
    """The gate refuses exactly the sentence's collision: a write-capable
    path reaching the zone — never a read, a writable elsewhere, or a
    grant that writes nowhere."""

    def test_read_only_operations_on_a_zone_member_are_not_writings(self) -> None:
        # The barrier's edge is between reading the zone and writing it.
        # The full read side, granted on a zone member to a component the
        # committed grant never mentions, is not a finding: the zone is
        # readable, and this gate refuses the write, not the eye.
        document = _with_extra_component(
            "discovery-orchestrator",
            "/zones/z0/contract",
            ["read", "list", "stat"],
        )
        assert merge_refusal(document) == ()
        # The foreign component's read grant contributes no writable path —
        # the committed components' work-area writes are beside the point
        # here, and stay where the stands class pins them.
        assert all(
            entry[0] != "discovery-orchestrator"
            for entry in agent_writable_paths(document)
        )

    def test_writable_paths_outside_the_zone_are_not_this_gates_refusal(
        self,
    ) -> None:
        # The sentence refuses the overlap, exactly. A write capability
        # on a fourth place outside the zone — a new Z1 work area, a
        # second artifact drop, a scratch directory — is §2's "agents
        # write to Z1 only" and feature 148's scope, not this gate's: it
        # does not audit where else the agents write, and refusing it here
        # would be refusing a sentence the spec keeps elsewhere.
        document = _grant_document()
        for component, credential, path in (
            ("signal-sandbox", "signal-sandbox-role", "/zones/z1/new-box/work"),
            ("policy-runtime", "policy-runtime-role", "/zones/z3/artifacts/shared"),
        ):
            for block in document["components"]:
                if block["name"] != component:
                    continue
                for granted in block["credentials"]:
                    if granted["name"] == credential:
                        granted["permissions"].append(
                            {"path": path, "operations": ["create", "write"]}
                        )
        document["components"].append(
            {
                "name": "dreaming-orchestrator",
                "credentials": [
                    {
                        "name": "dreaming-role",
                        "permissions": [
                            {"path": "/var/tmp/dream-scratch", "operations": ["write"]}
                        ],
                    }
                ],
            }
        )
        assert merge_refusal(document) == ()

    def test_a_grant_that_writes_nowhere_has_no_overlap(self) -> None:
        # The collision is the capability, not the existence: a document
        # whose every permission is read-side — a component granted
        # nothing but eyes — holds no writable path, and the merge stands.
        # A gate that refused grants for existing would refuse every
        # document that prepares one, which is not the sentence it
        # enforces.
        document = _grant_document()
        for block in document["components"]:
            for granted in block["credentials"]:
                granted["permissions"] = [
                    {"path": "/zones/z0/contract", "operations": ["read", "list"]}
                ]
        assert merge_refusal(document) == ()

    def test_a_document_that_cannot_be_walked_is_not_silently_stood(self) -> None:
        # The walk reads the grant's canonical shape and nothing else: a
        # document that carries no readable components yields no writable
        # paths and no overlap finding — the compile's refusal is that
        # document's fate, the member suite's subject, not this gate's.
        # But a document that names no zone is this gate's finding: the
        # geometry half fails closed where the overlap half has no
        # subject, so silence never certifies a zone the grant forgot to
        # say.
        assert merge_refusal({}) == ()
        drifts = geometry_refusal({})
        assert any(
            drift.face == "grant" and drift.subject == "immutable_zone"
            for drift in drifts
        )
        # And the mount's members are still named — against a document that
        # pins nothing, every member gap is the grant face's, six findings
        # that say the document forgot the zone rather than moved it.
        assert {
            drift.subject for drift in drifts if drift.face == "grant"
        } == {"immutable_zone", *(f"member {member}" for member in ZONE_MEMBERS)}
