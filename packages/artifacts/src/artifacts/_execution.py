"""The executed signal source plus its execution trace — feature 173's pair.

app_spec.xml, "Tree & Artifact Persistence", feature 173: *System
persists the executed signal source plus an execution trace alongside
every stored artifact.*  docs/nullius-tech-architecture.md §9.2 draws
the two lines of the layout that sentence names:

.. code-block:: text

    /artifacts/<campaign_id>/<node_id>/
      signal_returns.parquet    # per-symbol, per-period, post-cost
      ic_series.parquet
      turnover_series.parquet
      decay_profile.json
      regime_attribution.json
      exec_trace.json           ← the execution trace
      code.py                   ← the executed signal source

Every other file in that directory is *derived* data — the post-cost
returns, the IC and turnover series, the decay and regime splits one
execution measured.  These two are the only records of the *execution
itself*: ``code.py`` is the exact module text the sandbox ran, and
``exec_trace.json`` is the trace of that run — the deterministic
fingerprint the evaluator's final step renders from the run's
provenance (feature 85: node, campaign, sealed snapshot, evaluator
hash, fee schedule, horizons, ``charges_budget``, the steps the run
reached).  A stored artifact without the pair is a set of numbers
nobody can account for, and §1 is the reason that matters: the replay
engine is granted read access to this store and *nothing else* — not
the evaluator, not the sandbox — so what replay needs to know about
the run that produced a node's numbers has to live in the node's
directory or nowhere.  §9.1 keeps the run's *identity* (``code_hash``,
the agent triple, the hashes) in the tree row; the run's *bytes and
behaviour* live here, which is what "alongside" in the feature's
sentence is doing: same directory, same two keys, one artifact.

**The pair rides feature 169's write path; it is not a second one.**
:func:`persist_execution` stages both files through
:meth:`~artifacts.ArtifactStore.write` into the node's staged set —
invisible to every read, exactly like every other file the writer
stages — and the node's :meth:`~artifacts.ArtifactStore.commit`
publishes them alongside everything else as one directory.  There is
no second commit point, no sidecar collection, no separate provenance
store: a failure before the commit publishes nothing (the pair rolls
back with :meth:`~artifacts.ArtifactStore.discard` like any staged
file), and a refresh replaces the pair wholesale with the rest of the
directory, so a re-persisted node never carries the retry's numbers
beside the first attempt's source.  The layer this module adds is the
*pairing* and the read side, on the store's API rather than beside it
— the same place features 170-172's Parquet and JSON renderers layer.

**"Plus" is the contract: one operation, both halves.**  The feature
does not say the store *may* hold a source and *may* hold a trace; it
says the system persists the one *plus* the other, and the failure
mode that sentence exists to close is the half pair — a ``code.py``
whose execution nobody traced, or an ``exec_trace.json`` describing
bytes the directory does not hold.  So :func:`persist_execution`
takes both and refuses either alone: the source and the trace are
keyword-only arguments a caller cannot transpose, a source that is
not module text is refused by name, a trace that is not a JSON object
is refused by name, and every refusal lands *before the first staged
byte* — a refused pair stages nothing, not even the half that was
well-formed.  (The underlying store stays feature 169's general
bytestore; a caller that stages one name by hand can still do it.
What this layer owes is that its own operation cannot produce the
accident, and that the read side can *name* the accident when it
finds one — :func:`execution_is_persisted` answers the feature's
invariant for a published node, and the per-half readers refuse with
the missing half named.)

**The trace's vocabulary is the evaluator's; the pair's spelling is
this module's.**  Feature 85 owns what an ``exec_trace.json`` *says*;
this module owns that it is a JSON object of string keys, rendered to
canonical bytes — :func:`json.dumps` with ``sort_keys=True`` and the
compact separators, the spelling every canonical JSON writer in this
workspace uses, so two equal traces stage equal bytes and a replay
comparing stored traces compares content, not key order.  Non-finite
floats are refused (``allow_nan=False``): ``nan`` is not JSON, and a
fingerprint a parser must round-trip cannot carry it.  One agreement
check reaches into the vocabulary anyway, because it is an *addressing*
fact rather than a content one: when the trace carries a ``node_id``
or ``campaign_id`` key, its value must be the key the pair is staged
under.  A trace naming node B filed under node A's directory is
precisely the misfiling provenance exists to prevent — the directory
would answer "whose run was this?" with the wrong name, and every
later join (the tree row's ``artifact_uri``, the campaign loads of
features 174-180) would read it back wrong.  A trace carrying neither
key is accepted, not guessed at: the evaluator's fingerprint carries
both, but this layer does not demand vocabulary it does not own.

**The source is text, because its hash is the node's identity.**
§9.1 types the tree row's ``code_hash CHAR(64) NOT NULL`` and every
writer in this workspace fills it with
``hashlib.sha256(source.encode("utf-8")).hexdigest()`` — the
evaluator's step 6 is the reference spelling, and feature 179's
:func:`~artifacts.canonical_code_hash` is the value's canonical form.
:func:`source_code_hash` is that derivation from this side of the
boundary: the layer that persists ``code.py`` is the one place the
hash of *the bytes actually persisted* can be taken, so the row and
the directory cannot disagree about which code a node ran.  The
source is refused as bytes rather than accepted, for the same reason:
bytes passed through would make two spellings of ``code.py``'s
content (as-given and encoded) and untie the hash from the file.  A
caller holding bytes decodes them first; the module text is what the
sandbox executed and what the hash is over.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from ._dedup import canonical_code_hash
from ._errors import (
    ArtifactStoreError,
)
from ._keys import (
    validate_campaign_id,
    validate_node_id,
)
from ._store import ArtifactStore

__all__ = [
    "SOURCE_FILENAME",
    "TRACE_FILENAME",
    "executed_source",
    "execution_is_persisted",
    "execution_trace",
    "persist_execution",
    "source_code_hash",
]

#: The §9.2 name of the executed signal source — the exact module text
#: the sandbox ran, persisted beside the numbers it produced.  Spelled
#: once here so the write path, the read side and the tests this feature
#: owns cannot drift apart on what the file is called.
SOURCE_FILENAME = "code.py"

#: The §9.2 name of the execution trace — the run's fingerprint as
#: JSON.  The same single spelling, for the same reason.
TRACE_FILENAME = "exec_trace.json"

#: The trace keys that name the node and campaign the trace
#: fingerprints.  The evaluator's trace carries both, and the one
#: content check this layer makes is that, when present, they agree
#: with the keys the pair is staged under — the addressing fact a
#: misfiled trace would get wrong.
TRACE_NODE_KEY = "node_id"
TRACE_CAMPAIGN_KEY = "campaign_id"


# -- The write half: the pair, staged as one --------------------------------------


def persist_execution(
    store: ArtifactStore,
    campaign_id: str,
    node_id: str,
    *,
    source: str,
    trace: Mapping[str, Any],
) -> tuple[Path, Path]:
    """Stage the executed source and its trace alongside the node's artifact.

    The feature's sentence as one call over feature 169's staged write
    path: ``code.py`` and ``exec_trace.json`` join whatever else the
    writer has staged for the node, invisible to every read until the
    node's :meth:`~artifacts.ArtifactStore.commit` publishes the staged
    set — at which point the pair sits alongside every stored artifact
    file, in the one directory the node's two keys address.  Returns
    the two staged paths, source first, for a caller that wants to name
    what it staged; the commit, not this call, is the publication.

    Both halves are keyword-only, because the pair is the contract: a
    caller cannot transpose a source and a trace it had to name, and
    neither half is optional — staging the source without the trace
    (or the trace without the source) is the half pair the feature
    exists to prevent, so the operation that would produce it does not
    exist.  Every refusal — a malformed key, a source that is not
    module text, a trace that is not a JSON object of string keys, a
    trace whose ``node_id``/``campaign_id`` names a node other than
    the one it is staged under, a value no JSON renderer may emit —
    lands *before the first staged byte*, so a refused pair leaves the
    staged set exactly as it was.  Staging the pair again re-stages
    both files, keeping the last bytes, exactly as re-staging any
    filename does; a commit then publishes the latest pair, never a
    splice of two.
    """
    # The keys first, so a malformed one refuses as a key failure
    # rather than as a payload complaint: the two-segment key is the
    # layout (feature 169), and it outranks everything staged through it.
    validate_campaign_id(campaign_id)
    validate_node_id(node_id)
    text = _validated_source(source)
    body = _validated_trace(trace, campaign_id=campaign_id, node_id=node_id)
    rendered = _render_trace(body)
    staged_source = store.write(campaign_id, node_id, SOURCE_FILENAME, text)
    staged_trace = store.write(campaign_id, node_id, TRACE_FILENAME, rendered)
    return staged_source, staged_trace


def source_code_hash(source: str) -> str:
    """The code hash of an executed signal source, spelled canonically.

    §9.1's ``code_hash CHAR(64) NOT NULL`` — the column feature 179
    deduplicates a proposal against — is the sha256 hexdigest of the
    source text encoded UTF-8 (the evaluator's step 6 is the reference
    spelling), and this is that derivation from the artifact side of
    the boundary: the answer a caller stages as ``code.py`` and the
    answer the tree row carries are one value, taken once.  The result
    is passed through :func:`~artifacts.canonical_code_hash` so the
    spelling is checked by the one module that owns it — for a real
    hexdigest the check cannot fail, but the contract (64 lowercase
    hex characters, the value the tree stores) is stated where it is
    enforced rather than assumed.

    The source is validated exactly as :func:`persist_execution`
    validates it — text, and not empty — because a hash of a value the
    write path would refuse is the identity of a ``code.py`` that will
    never exist.
    """
    text = _validated_source(source)
    return canonical_code_hash(
        hashlib.sha256(text.encode("utf-8")).hexdigest()
    )


# -- The read half: the pair, answered by the same keys ----------------------------


def executed_source(store: ArtifactStore, campaign_id: str, node_id: str) -> str:
    """The node's executed signal source, read back as module text.

    The read side of the pair's first half: the bytes persisted as
    ``code.py``, decoded as the UTF-8 they were staged as, so a caller
    — replay reconstructing a run, a reconciliation sweep, feature
    179's gate re-deriving the hash the row claims — holds the exact
    text the sandbox executed.  Refuses with
    :class:`~artifacts._errors.ArtifactNotFoundError` when the node
    holds no directory or its directory holds no ``code.py``, the
    refusal naming which half is missing so a node that never
    persisted stays distinguishable from one persisted without its
    provenance.  Bytes that are not UTF-8 refuse rather than decode
    lossily: a source that cannot be read as text cannot be hashed
    into the identity the tree row carries, and guessing at it is how
    the directory and the row come to disagree.
    """
    raw = store.read(campaign_id, node_id, SOURCE_FILENAME)
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ArtifactStoreError(
            f"the executed signal source of node {node_id!r} of campaign "
            f"{campaign_id!r} is not UTF-8 text, so it is not the module "
            f"text any writer of this store staged: {exc}; the source's "
            "hash is the node's identity in the tree store, and bytes "
            "that cannot be decoded cannot be hashed into it"
        ) from exc


def execution_trace(
    store: ArtifactStore, campaign_id: str, node_id: str
) -> dict[str, Any]:
    """The node's execution trace, read back as the JSON object it is.

    The read side of the pair's second half: the bytes persisted as
    ``exec_trace.json``, parsed, and answered as the mapping the
    renderer staged — the fingerprint replay reconstructs a run from
    without reaching the evaluator (§1).  Refuses with
    :class:`~artifacts._errors.ArtifactNotFoundError` when the node
    holds no directory or its directory holds no ``exec_trace.json``,
    naming the missing half.  Bytes that are not JSON, or JSON that is
    not an object, refuse with
    :class:`~artifacts._errors.ArtifactStoreError` rather than
    answering a stand-in: a trace is the record of one execution, and
    a value that cannot be the renderer's output is a file this
    module's write path never staged.
    """
    raw = store.read(campaign_id, node_id, TRACE_FILENAME)
    try:
        parsed = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ArtifactStoreError(
            f"the execution trace of node {node_id!r} of campaign "
            f"{campaign_id!r} is not readable as JSON: {exc}; a trace is "
            "the fingerprint of one execution, and bytes no renderer "
            "emitted are a file this member's write path never staged"
        ) from exc
    if not isinstance(parsed, dict):
        raise ArtifactStoreError(
            f"the execution trace of node {node_id!r} of campaign "
            f"{campaign_id!r} is not a JSON object — got "
            f"{type(parsed).__name__}; an execution trace is the object "
            "the evaluator's renderer emits, and anything else is a "
            "file this member's write path never staged"
        )
    return parsed


def execution_is_persisted(
    store: ArtifactStore, campaign_id: str, node_id: str
) -> bool:
    """Whether the node's published artifact carries the whole pair.

    The feature's invariant, answered as a fact: the node's directory
    is published *and* holds both ``code.py`` and ``exec_trace.json``
    — the executed source plus its trace, alongside every other stored
    artifact file.  ``False`` for a node nothing was published for
    (staged-but-uncommitted is invisible by design, the discipline
    feature 169 states), and ``False`` for the half pair — a directory
    holding one of the two names is exactly the state this check
    exists to find, whether a hand-staged write or a interrupted
    refresh produced it.  A reconciliation sweep, or a replay about to
    trust a campaign's artifacts, asks this rather than catching
    refusals, because "absent" and "short one half" are both facts to
    report, not exceptions to handle.
    """
    if not store.has_node(campaign_id, node_id):
        return False
    held = store.files(campaign_id, node_id)
    return SOURCE_FILENAME in held and TRACE_FILENAME in held


# -- The pair's validation, spelled once for every seam above ----------------------


def _validated_source(source: Any) -> str:
    """Return ``source`` as the module text it must be, or refuse it.

    The executed signal source is text — the module the sandbox
    executed, hashed into the tree row's ``code_hash`` over its UTF-8
    encoding — so bytes are refused with a pointer to decode (passing
    them through would untie the file's bytes from the hash the row
    carries), any other type is refused by name, and a source with no
    characters at all is refused because it names no execution: an
    empty module is not code that ran.  Whitespace-and-comments only
    is accepted, as it should be — the store holds bytes, and what
    makes a module *valid* Python is the sandbox's question, not the
    directory store's.
    """
    if isinstance(source, bytes):
        raise ArtifactStoreError(
            "the executed signal source is module text, not bytes — got a "
            "bytes value; decode it to str before persisting it, so the "
            "bytes staged as code.py and the sha256 the tree row's "
            "code_hash column carries are one spelling of one source"
        )
    if not isinstance(source, str):
        raise ArtifactStoreError(
            f"the executed signal source is module text — got "
            f"{type(source).__name__} {source!r}; code.py holds the exact "
            "module the sandbox executed, and a value that is not its "
            "text is not the source of the run the trace fingerprints"
        )
    if not source.strip():
        raise ArtifactStoreError(
            f"the executed signal source of a node cannot be empty — got "
            f"{source!r}; code.py is the module the sandbox executed, and "
            "source with no characters is no execution at all"
        )
    return source


def _validated_trace(
    trace: Any, *, campaign_id: str, node_id: str
) -> dict[str, Any]:
    """Return ``trace`` as the JSON object it must be, or refuse it.

    Structure, not vocabulary: a trace is a mapping of string keys to
    JSON-serializable values (what the fields *mean* is feature 85's,
    and this layer does not demand keys it does not own).  A non-string
    key is refused rather than stringified — ``json.dumps`` would
    silently turn ``{1: ...}`` into ``{"1": ...}``, and a trace whose
    keys changed spelling between the caller and the file is a
    fingerprint nothing can compare.  The one vocabulary check that is
    this layer's to make is the addressing one: a trace carrying
    ``node_id``/``campaign_id`` must name the node it is staged under,
    because a trace filed under the wrong node's key is the misfiling
    provenance exists to prevent.
    """
    if not isinstance(trace, Mapping):
        raise ArtifactStoreError(
            f"an execution trace is a JSON object — got "
            f"{type(trace).__name__} {trace!r}; exec_trace.json holds the "
            "fingerprint of one execution as a mapping, and a trace that "
            "is not one cannot be rendered beside the source it describes"
        )
    body: dict[str, Any] = {}
    for key, value in trace.items():
        if not isinstance(key, str):
            raise ArtifactStoreError(
                f"an execution trace's keys are strings — got {key!r} "
                f"({type(key).__name__}); json would silently stringify "
                "it, and a fingerprint whose keys changed spelling "
                "between the caller and the file is one nothing can "
                "compare against"
            )
        body[key] = value
    for key, staged_under in (
        (TRACE_NODE_KEY, node_id),
        (TRACE_CAMPAIGN_KEY, campaign_id),
    ):
        if key in body and body[key] != staged_under:
            raise ArtifactStoreError(
                f"the execution trace names {key}={body[key]!r}, but it "
                f"is being staged under {key}={staged_under!r}; a trace "
                "filed beside a node it does not fingerprint is the "
                "misfiling the pair exists to prevent — every later "
                "reader joins the directory by these keys, and would "
                "answer 'whose run was this?' with the wrong name"
            )
    return body


def _render_trace(body: dict[str, Any]) -> str:
    """Render the validated trace to canonical JSON text.

    The one byte spelling of a trace: :func:`json.dumps` with
    ``sort_keys=True`` and the compact separators — the canonical-JSON
    spelling every member of this workspace that writes JSON for a
    hash or a comparison uses — so two equal traces stage equal bytes
    and key order is never part of a trace's identity.  A value no
    renderer may emit (an unserializable object, a non-finite float —
    ``allow_nan=False``, because ``nan`` is not JSON and a fingerprint
    a parser must round-trip cannot carry it) is refused here rather
    than staged as half a file.
    """
    try:
        return json.dumps(
            body, sort_keys=True, separators=(",", ":"), allow_nan=False
        )
    except (TypeError, ValueError) as exc:
        raise ArtifactStoreError(
            f"an execution trace must be renderable as JSON — {exc}; "
            "exec_trace.json is the fingerprint replay parses back, and "
            "a value no JSON renderer may emit is not a fact about the "
            "run that can be stored beside it"
        ) from exc
