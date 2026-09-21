"""The artifacts plugin's error taxonomy.

One base class (:class:`ArtifactsError`) so a caller — the evaluator's
final pipeline step, the replay engine §1 grants read access to this
store and nothing else, an operator script, a later feature in this
category — can catch every failure of the artifact path with a single
``except``.  The subclasses split by *which contract* was violated, not
by which line of code failed:

* :class:`ArtifactKeyError` — the layout's key contract (app_spec.xml
  feature 169).  A ``campaign_id``, ``node_id`` or ``filename`` that
  cannot serve as the one path segment it is: empty, whitespace-only,
  ``.`` or ``..``, carrying a separator or a NUL, or squatting on the
  dot-prefixed namespace the store reserves for its own plumbing.
  The feature's whole sentence is *"keyed by campaign_id then
  node_id"* — the key **is** the layout — so a key that would silently
  reshape the tree (a ``node_id`` of ``a/b`` nesting a third level, a
  ``..`` escaping the store root) is refused at the boundary, before
  any directory is touched, rather than written down as a path nobody
  can key back to a node.  The same refusal guards the read side: a
  traversal dressed as a lookup finds no directory to list.

* :class:`ArtifactStoreError` — the store's write contract.  The root
  is unusable (an empty path, a root the environment refuses to name),
  a payload is not bytes a file can hold, a commit was asked for with
  nothing staged, or the filesystem refused a create, write or rename
  the persistence path depends on.  Raised rather than swallowed
  because a node whose artifact directory silently failed to persist is
  exactly the accident feature 169 exists to close: the tree store
  would carry a row whose ``artifact_uri`` names a directory that was
  never written, and the replay that later reads it would score a node
  against nothing.  The original :class:`OSError` always rides along as
  ``__cause__`` when one exists, because "the disk said no" and "the
  request was incoherent" are different facts an operator acts on
  differently.

* :class:`ArtifactNotFoundError` — the read side's fact, not failure.
  A node the store holds no directory for, or a file the node's
  directory does not carry.  Distinct from :class:`ArtifactKeyError`
  (the *key* was well-formed; the world just does not hold it) and from
  :class:`ArtifactStoreError` (nothing failed — the store answered a
  question about its contents).  Kept separate so a caller can treat
  "unknown node" the way §7.2's route treats its 404 — a fact to
  report — while still catching every genuine breakage with the base
  class.  The message names the campaign, the node and, when it was a
  file that was asked for, the filename, so the operator reading it can
  tell a missing *node* from a node that is missing *one file* — the
  half-written state the staged write path exists to prevent.

* :class:`ArtifactProposalError` — the dedup gate's contract (app_spec.xml
  feature 179).  A *proposed* node that cannot pass the gate that stands
  between it and its trial: the code hash it carries is not a sha256
  hexdigest, or the campaign it must be deduplicated within cannot be
  named.  Raised before the tree store is touched, so a proposal that
  cannot state its identity spends no sequence number and leaves no
  reservation behind.  Its subclass
  :class:`ArtifactDeduplicatedError` is the feature's own decision — an
  exact duplicate of a code the campaign already stores — split out so a
  caller can tell "this proposal is malformed" from "this proposal is a
  repeat" and report them differently, while a caller that only needs to
  know the proposal was refused catches the base.

Every message names the offending value and the contract it broke, in
the same discipline as the snapshot and null-oracle taxonomies: these
errors are operational signals for a system whose replay determinism
rests on the bytes this store holds, so a failure of the artifact path
must be *speakable*, not merely loggable.
"""

from __future__ import annotations

__all__ = [
    "ArtifactDeduplicatedError",
    "ArtifactKeyError",
    "ArtifactNotFoundError",
    "ArtifactProposalError",
    "ArtifactStoreError",
    "ArtifactsError",
]


class ArtifactsError(Exception):
    """Base class for every failure of the artifact path."""


class ArtifactKeyError(ArtifactsError):
    """A campaign_id, node_id or filename cannot serve as its path segment.

    The two-segment key *is* the layout of feature 169 —
    ``<campaign_id>/<node_id>`` — so a value that is not exactly one
    safe directory component is refused before anything is created:
    empty or whitespace-only (a directory nobody could name back),
    ``.`` or ``..`` (a step outside the store), anything carrying ``/``
    or ``\\`` (a key trying to be two segments), a NUL (a path the
    kernel refuses), or a leading dot (the namespace — ``.staging``
    above all — this store reserves for its own plumbing, the same way
    the snapshot member's ``.sealing-<random>`` working directories
    live beside the snapshots they build).  Non-string values are
    refused rather than stringified, because a coerced ``Path`` or
    ``int`` would key a directory its caller cannot ask for again by
    the value it actually holds.
    """


class ArtifactStoreError(ArtifactsError):
    """The store could not persist, publish or answer as asked.

    An unusable root, a payload that is not bytes a file can hold, a
    commit with nothing staged, or an :class:`OSError` from the
    filesystem at any step of the staged write path.  The refusal is
    loud by design: this member's one job is that a node's artifact
    directory *exists*, keyed where the tree store's ``artifact_uri``
    says it is, and a persist that quietly did not happen would leave
    the pipeline's step 12 believing it wrote an artifact replay can
    never read.
    """


class ArtifactNotFoundError(ArtifactsError):
    """The store holds no such node directory, or it holds no such file.

    A fact about the store's contents, reported rather than raised as a
    breakage: the campaign and node keys were well-formed (a malformed
    one is :class:`ArtifactKeyError`'s to refuse), the store answered,
    and the answer is that nothing is persisted there.  Naming the
    campaign, the node and — for a file ask — the filename keeps a
    missing *node* distinguishable from a node missing *a file*, which
    is the distinction a reconciliation sweep wants.
    """


class ArtifactProposalError(ArtifactsError):
    """A proposed node cannot pass the dedup gate feature 179 puts before it.

    The gate's contract: :func:`artifacts._dedup.reject_duplicate` and
    :meth:`artifacts._dedup.CodeHashIndex.reserve` deduplicate a proposal
    against the campaign's stored ``code_hash`` values, and a value that
    cannot take part in that comparison is refused rather than skipped —
    a proposal whose code hash is truncated, non-hex, non-string or
    prefixed with an algorithm name names no stored node, so a gate that
    guessed at it would pass every duplicate it was handed.  Raised before
    the tree store is written, so nothing is half-reserved.

    Distinct from :class:`ArtifactStoreError` (the *store* failed — this
    refusal says the store was never reached) and from
    :class:`ArtifactKeyError` (the §9.2 layout's key contract, a different
    address entirely).
    """


class ArtifactDeduplicatedError(ArtifactProposalError):
    """The proposal is an exact duplicate of code the campaign already stores.

    app_spec.xml feature 179: *System deduplicates a proposed node against
    stored ``code_hash`` values, which rejects an exact duplicate before it
    charges a trial.*  The refusal's message begins with the
    ``duplicate_code_hash`` code so the rejection is greppable by the
    feature that defines it.

    A *fact about the proposal*, not a breakage: the gate worked, the
    proposal was compared against the campaign's tree, and it is the same
    code a node already holds — so no trial was charged for it.  That is
    the difference between this class and its parent: a proposal that
    cannot state its code identity is malformed and can be fixed by the
    caller, while a duplicate is a *verdict* the caller acts on by
    proposing something structurally different (§14.1's anti-convergence
    clause is the same rule from the search side).  Catching
    :class:`ArtifactProposalError` covers both; catching this one separates
    the verdict from the malformed input.
    """
