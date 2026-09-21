"""The decay profile and the regime attribution — §9.2's two JSON documents.

app_spec.xml, "Tree & Artifact Persistence", feature 172: *System
persists decay_profile and regime_attribution as JSON inside the node
artifact directory.*  docs/nullius-tech-architecture.md §9.2 draws the
two lines that sentence names, in the middle of the node's one
directory:

.. code-block:: text

    /artifacts/<campaign_id>/<node_id>/
      signal_returns.parquet    # per-symbol, per-period, post-cost
      ic_series.parquet
      turnover_series.parquet
      decay_profile.json        ← the edge, resolved over horizons
      regime_attribution.json   ← the edge, resolved over regimes
      exec_trace.json
      code.py

**One thing, two axes.**  docs/alpha-engine-prd.md's artifact block
gives both shapes in two lines — ``decay_profile: array    # IC at
h = 1, 2, 5, 10, 20 periods`` and ``regime_attribution: dict`` — and
what they share is what makes them one module rather than two: each is
a *description of the node's edge along one axis*.  The profile
resolves the edge over the horizon axis — how much of the information
coefficient survives to 1, 2, 5, 10 and 20 periods — and the
attribution resolves the same edge over the regime axis, the
per-stratum, per-horizon split §9.2 files beside it.  Every other file
in the directory is a *series* keyed by date (``ic_series``,
``turnover_series``, ``signal_returns`` — features 170-171's Parquet),
a *record* of the run (``exec_trace.json``) or the run's *source*
(``code.py`` — feature 173); these two are the documents a policy
reads to ask "what shape is this edge?" without walking a panel.  The
evaluator produces both at its measurement step — §6.1's ``8.
compute_metrics    IC series, IR, turnover, decay, capacity, regime
attribution`` — and this module owns where they land and in what bytes.

**One operation per document; the pair is not the contract.**  Feature
173's ``plus`` makes its source and its trace one operation that cannot
stage a half, because neither half is a record of an execution without
the other.  This feature's sentence says *and*, not *plus*, and the
difference is not a typo: the two documents are produced at two
different pipeline steps (feature 81 computes the decay profile,
feature 82 the capacity estimate and the attribution), a node's run can
reach one and not the other, and each is independently readable — the
live loop tracks a stored profile against a forward one without ever
reading a regime split (§9.2's decay row, and the PRD's).  So each
document gets its own operation, its own reader and its own invariant
check here, and :func:`persist_decay_profile` deliberately does **not**
insist on an attribution beside it.  A caller that wants both persists
both; a caller that has only a profile persists a profile.

**The axis is positional; its *length* is not this layer's to demand.**
The array is the stored spelling because that is how the live loop
consumes it — entry by entry against a forward profile — so a mapping
keyed by horizon would have to be re-aligned by every reader, and this
layer refuses one rather than persisting a document whose axis changed
shape.  What it does *not* do is demand the array be five entries long:
the axis ``h = 1, 2, 5, 10, 20`` is feature 81's
(:data:`evaluator._decay.DECAY_HORIZONS`), this member may not import
that package (the workspace contract — neither member imports the
other), and a horizon list restated here would be a second spelling of
the axis that could drift from the one the evaluator measures over.
Positional order is preserved through the render; an entry that is not
a number or a JSON ``null`` is refused by position, because
"un-measured" is ``None`` and never ``0.0``, and a fabricated zero at
horizon 20 is the promotion-relevant lie feature 81's own refusal
exists to prevent.

**The bytes are canonical, so a stored document is a fingerprint.**  A
render is :func:`json.dumps` with ``sort_keys=True`` and the compact
separators, with ``allow_nan=False`` — the canonical-JSON spelling
every member of this workspace that writes JSON for a comparison uses,
and the spelling :func:`artifacts.persist_execution` gives the trace
beside these files.  Sorting keys is what makes the attribution
comparable: the evaluator renders strata and horizons in sorted order
already, and sorting again here means two equal attributions built in
different insertion orders stage *identical bytes*, so a replay
comparing stored attributions compares content and never key order.
It cannot reorder the profile, because the profile is an array and
``sort_keys`` does not touch list order — which is exactly why the
positional spelling is safe under a canonical renderer.  ``nan`` and
``inf`` are refused rather than written: they are not JSON, a reader
must round-trip this document, and the evaluator's own reader refuses a
non-finite entry, so bytes this layer could emit would be bytes its
owner cannot read back.

**The read side answers the same shapes, and refuses what this writer
cannot emit.**  :func:`decay_profile` answers the array,
:func:`regime_attribution` the object, both by the node's same two keys
and both through the store's read surface — the one §1 grants the
replay engine.  A node with no directory, or a directory short the
named file, refuses with :class:`~artifacts._errors.ArtifactNotFoundError`
naming which is missing.  Bytes that are not JSON, or JSON of the wrong
top-level shape, refuse with :class:`~artifacts._errors.ArtifactStoreError`
rather than answering a stand-in — and so does a document carrying
``NaN``/``Infinity``, Python's own extension to the grammar: no
renderer of this layer can emit one, so a document holding one did not
come from this writer and is not something to hand a caller as a
measurement.

**Both ride feature 169's write path; neither is a second one.**
:func:`persist_decay_profile` and :func:`persist_regime_attribution`
stage their file through :meth:`~artifacts.ArtifactStore.write` and the
node's :meth:`~artifacts.ArtifactStore.commit` publishes everything
staged for the node as one directory.  There is no second commit point
and no sidecar: a failure before the commit publishes nothing, a
:meth:`~artifacts.ArtifactStore.discard` rolls both back with every
other staged file, and a refresh replaces them wholesale — so a
re-persisted node never carries the retry's profile beside the first
attempt's attribution.

**The same names exist in the evaluator, on a different store.**  That
package's decay store spells a ``persist_decay_profile`` too, and its
operation writes the relational row the profile is *measured into*;
this one writes the §9.2 document the profile is *filed as*.  Two
stores, two facts, and the workspace contract keeps them from being
reconciled by an import — a caller holding both namespaces reaches the
one it means by name, and the docstrings here and there are the
distinction's only home.
"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from ._errors import ArtifactStoreError
from ._keys import (
    validate_campaign_id,
    validate_node_id,
)
from ._store import ArtifactStore

__all__ = [
    "DECAY_PROFILE_FILENAME",
    "REGIME_ATTRIBUTION_FILENAME",
    "decay_profile",
    "decay_profile_is_persisted",
    "persist_decay_profile",
    "persist_regime_attribution",
    "regime_attribution",
    "regime_attribution_is_persisted",
]

#: The §9.2 name of the decay profile — the node's information
#: coefficient at each horizon, as the positional array the live loop
#: consumes.  Spelled once here so the write path, the read side and the
#: tests this feature owns cannot drift apart on what the file is called.
DECAY_PROFILE_FILENAME = "decay_profile.json"

#: The §9.2 name of the regime attribution — the node's per-stratum,
#: per-horizon split as JSON.  The same single spelling, for the same
#: reason.
REGIME_ATTRIBUTION_FILENAME = "regime_attribution.json"


# -- The write half: one operation per document ------------------------------------


def persist_decay_profile(
    store: ArtifactStore,
    campaign_id: str,
    node_id: str,
    profile: Any,
) -> Path:
    """Stage the node's decay profile as §9.2's ``decay_profile.json``.

    The feature's first document, staged through feature 169's write
    path: the profile joins whatever else the writer has staged for the
    node, invisible to every read until the node's
    :meth:`~artifacts.ArtifactStore.commit` publishes the staged set —
    at which point it sits inside the node's one directory, keyed by
    the same two ids every reader joins on.  Returns the staged path for
    a caller that wants to name what it staged; the commit, not this
    call, is the publication.

    ``profile`` is the rendered array feature 81's step produces — the
    evaluator's ``render_decay_profile`` answers exactly this shape, one
    entry per horizon in the axis's order, ``None`` for a horizon the
    window was too short to measure.  A mapping is refused rather than
    re-keyed (the axis is positional, and a mapping would have to be
    re-aligned by every reader), text is refused by name (a string is a
    sequence of characters, and ``json`` would render it as a JSON
    string — a document that measures nothing), a sequence carrying no
    entries is refused (an empty profile spans no horizon at all), and
    an entry that is neither a finite number nor ``None`` is refused by
    *position*, so the refusal names which horizon of the axis is wrong
    rather than merely that one is.  Every refusal lands before the
    first staged byte, so a refused profile leaves the staged set
    exactly as it was.  Staging the profile again re-stages the one
    file, keeping the last bytes, exactly as re-staging any filename
    does; a commit then publishes the latest profile, never a splice of
    two runs.
    """
    validate_campaign_id(campaign_id)
    validate_node_id(node_id)
    rendered = _render_document(
        _validated_profile(profile),
        filename=DECAY_PROFILE_FILENAME,
        campaign_id=campaign_id,
        node_id=node_id,
    )
    return store.write(
        campaign_id, node_id, DECAY_PROFILE_FILENAME, rendered
    )


def persist_regime_attribution(
    store: ArtifactStore,
    campaign_id: str,
    node_id: str,
    attribution: Any,
) -> Path:
    """Stage the node's regime attribution as ``regime_attribution.json``.

    The feature's second document, and the same discipline as the first:
    staged through feature 169's write path, published by the node's one
    commit, invisible until then.  Returns the staged path.

    ``attribution`` is the rendered mapping feature 82's step produces —
    the evaluator's ``render_regime_attribution`` answers
    ``{stratum: {horizon: {...}}}`` plus ``unattributed_dates``.
    Structure only is checked, exactly as feature 173 checks a trace's:
    the document is a JSON object of *string* keys, and a non-string key
    is refused rather than stringified, because ``json.dumps`` would
    silently turn ``{1: ...}`` into ``{"1": ...}`` and a stratum whose
    name changed spelling between the caller and the file is one no
    reader can join back to the regime it labels.  An attribution of no
    keys is refused — a split of nothing splits nothing, and a real
    render of feature 82's record always carries at least the
    ``unattributed_dates`` count.  The inner vocabulary is the
    evaluator's and is not demanded here; a value no JSON renderer may
    emit (an unserializable object, a non-finite float) is refused
    before the first staged byte.
    """
    validate_campaign_id(campaign_id)
    validate_node_id(node_id)
    rendered = _render_document(
        _validated_attribution(attribution),
        filename=REGIME_ATTRIBUTION_FILENAME,
        campaign_id=campaign_id,
        node_id=node_id,
    )
    return store.write(
        campaign_id, node_id, REGIME_ATTRIBUTION_FILENAME, rendered
    )


# -- The read half: the documents, answered by the same keys -----------------------


def decay_profile(
    store: ArtifactStore, campaign_id: str, node_id: str
) -> list[Any]:
    """The node's decay profile, read back as the positional array it is.

    The read side of the feature's first document: the bytes persisted
    as ``decay_profile.json``, parsed and answered as the list the
    renderer staged — entry *i* the information coefficient at the *i*-th
    horizon of feature 81's axis, ``None`` where the window was too
    short to measure.  A reader that needs the axis's horizons has them
    from the evaluator's package, which owns them; this layer owns the
    document and answers it in the order it was written.

    Refuses with :class:`~artifacts._errors.ArtifactNotFoundError` when
    the node holds no directory or its directory holds no
    ``decay_profile.json``, the refusal naming which is missing — so a
    node that never persisted stays distinguishable from one persisted
    without its profile.  Bytes that are not JSON, JSON that is not an
    array, or a document carrying ``NaN``/``Infinity`` refuse with
    :class:`~artifacts._errors.ArtifactStoreError` rather than answering
    a stand-in: the profile is one node's measurement along one axis, and
    a value this layer's writer cannot emit is a file this member never
    staged.
    """
    parsed = _read_document(
        store,
        campaign_id,
        node_id,
        DECAY_PROFILE_FILENAME,
        expected="array",
    )
    return parsed


def regime_attribution(
    store: ArtifactStore, campaign_id: str, node_id: str
) -> dict[str, Any]:
    """The node's regime attribution, read back as the object it is.

    The read side of the feature's second document: the bytes persisted
    as ``regime_attribution.json``, parsed and answered as the mapping
    the renderer staged — the per-stratum, per-horizon split replay and
    the promotion path read to ask *in which regimes does this edge
    exist?* without reaching the evaluator (§1).  Refuses with
    :class:`~artifacts._errors.ArtifactNotFoundError` when the node
    holds no directory or its directory holds no
    ``regime_attribution.json``, naming the missing half.  Bytes that
    are not JSON, JSON that is not an object, or a document carrying
    ``NaN``/``Infinity`` refuse with
    :class:`~artifacts._errors.ArtifactStoreError`.
    """
    parsed = _read_document(
        store,
        campaign_id,
        node_id,
        REGIME_ATTRIBUTION_FILENAME,
        expected="object",
    )
    return parsed


def decay_profile_is_persisted(
    store: ArtifactStore, campaign_id: str, node_id: str
) -> bool:
    """Whether the node's published artifact carries its decay profile.

    The feature's first document as a fact: the node's directory is
    published *and* holds ``decay_profile.json``.  ``False`` for a node
    nothing was published for — staged-but-uncommitted is invisible by
    design, the discipline feature 169 states — and ``False`` for a
    directory published without the profile, which is the state a
    reconciliation sweep exists to find.  Presence, not validity: a file
    this writer did not render is still a file at the name, and a sweep
    that wants its *content* checked asks :func:`decay_profile` and gets
    the refusal that names what is wrong with it.
    """
    return _is_persisted(
        store, campaign_id, node_id, DECAY_PROFILE_FILENAME
    )


def regime_attribution_is_persisted(
    store: ArtifactStore, campaign_id: str, node_id: str
) -> bool:
    """Whether the node's published artifact carries its regime attribution.

    The second document's invariant, answered the same way and kept
    *separate* from the first's: the two are produced at two pipeline
    steps and each is independently readable, so a node carrying a
    profile and no attribution is a fact a caller may legitimately
    meet — and asking one question here must not silently answer for
    the other.
    """
    return _is_persisted(
        store, campaign_id, node_id, REGIME_ATTRIBUTION_FILENAME
    )


# -- The documents' validation, spelled once for every seam above ------------------


def _validated_profile(profile: Any) -> list[Any]:
    """Return ``profile`` as the positional array it must be, or refuse it.

    The shape is the artifact's: §9.2 files the profile as a JSON array,
    the PRD writes its axis out (``h = 1, 2, 5, 10, 20``), and the live
    loop consumes it entry by entry — so the value must be a sequence
    this layer can render as an array, and a mapping is refused with a
    pointer at the positional spelling rather than quietly re-keyed.
    Text is refused separately from "not a sequence" because
    :class:`str` *is* a sequence of characters and ``json.dumps`` would
    render it as a JSON string: a document that is a string is not a
    profile that measures anything, and the caller needs to be told
    which of the two mistakes it made.

    Every entry must be a finite number or ``None``, checked *by
    position* so the refusal names the horizon of the axis that is
    wrong.  ``None`` is the un-measured horizon and is carried; ``True``
    is refused even though :class:`bool` is an :class:`int` in Python —
    JSON has a boolean and a number, and a flag is not an information
    coefficient.  ``nan`` and ``inf`` are refused here rather than left
    to the renderer's ``allow_nan=False``, for the sake of the position
    in the message: the renderer would name the value, which for a
    hundred-entry array is not enough to find it.
    """
    if isinstance(profile, (str, bytes, bytearray)):
        raise ArtifactStoreError(
            f"a decay profile is a JSON array — got "
            f"{type(profile).__name__} {profile!r}; the array holds one "
            "entry per horizon, not the text of one, and json would "
            "render a string as a JSON string rather than as the axis "
            "the live loop reads entry by entry"
        )
    if isinstance(profile, Mapping):
        raise ArtifactStoreError(
            f"a decay profile is a positional array, not a mapping — got "
            f"a {type(profile).__name__} keyed by "
            f"{', '.join(repr(key) for key in list(profile)[:5]) or 'nothing'}"
            "; the axis is the array's positions (feature 81), and a "
            "profile keyed by horizon would have to be re-aligned by "
            "every reader — render it as the array instead"
        )
    if not isinstance(profile, Sequence):
        raise ArtifactStoreError(
            f"a decay profile is a JSON array — got "
            f"{type(profile).__name__} {profile!r}; the profile is the "
            "information coefficient at each horizon, positionally, and "
            "a value that is not a sequence is not one"
        )
    entries = list(profile)
    if not entries:
        raise ArtifactStoreError(
            "a decay profile cannot be empty — got no entries; the "
            "array is positional over the horizons the node was "
            "measured at, and a profile with no positions measures no "
            "horizon at all"
        )
    for position, entry in enumerate(entries):
        if entry is None:
            continue
        if isinstance(entry, bool) or not isinstance(entry, (int, float)):
            raise ArtifactStoreError(
                f"a decay profile's entries are information "
                f"coefficients or null — got {entry!r} "
                f"({type(entry).__name__}) at position {position}; an "
                "un-measured horizon is null and never a stand-in "
                "value, and a coefficient is a number"
            )
        if not math.isfinite(entry):
            raise ArtifactStoreError(
                f"a decay profile's entries are finite — got {entry!r} "
                f"at position {position}; nan and inf are not JSON, a "
                "reader must round-trip this document, and an "
                "un-measured horizon is spelled null rather than a "
                "number that is not one"
            )
    return entries


def _validated_attribution(attribution: Any) -> dict[str, Any]:
    """Return ``attribution`` as the JSON object it must be, or refuse it.

    Structure, not vocabulary: the attribution is a mapping of string
    keys to JSON-serializable values — what the strata and horizons
    *mean* is feature 82's, and this layer does not demand keys it does
    not own.  A non-string key is refused rather than stringified,
    because ``json.dumps`` would silently turn ``{1: ...}`` into
    ``{"1": ...}`` and a stratum whose name changed spelling between the
    caller and the file is one no reader can join back to the regime it
    labels.  An object with no keys is refused: a render of feature 82's
    record always carries at least the ``unattributed_dates`` count, so
    an empty one is a document no writer of this layer's step produced,
    and a split of nothing is not a split.
    """
    if not isinstance(attribution, Mapping):
        raise ArtifactStoreError(
            f"a regime attribution is a JSON object — got "
            f"{type(attribution).__name__} {attribution!r}; "
            "regime_attribution.json holds the per-stratum split as a "
            "mapping, and a value that is not one is not the split "
            "feature 82 produced"
        )
    body: dict[str, Any] = {}
    for key, value in attribution.items():
        if not isinstance(key, str):
            raise ArtifactStoreError(
                f"a regime attribution's keys are strings — got {key!r} "
                f"({type(key).__name__}); json would silently "
                "stringify it, and a stratum whose name changed spelling "
                "between the caller and the file is one no reader can "
                "join back to the regime it labels"
            )
        body[key] = value
    if not body:
        raise ArtifactStoreError(
            "a regime attribution cannot be empty — got no keys; the "
            "document is the node's edge split by regime, and an "
            "attribution with no stratum attributes nothing to anywhere"
        )
    return body


def _render_document(
    body: Any, *, filename: str, campaign_id: str, node_id: str
) -> str:
    """Render a validated document to canonical JSON text.

    The one byte spelling of both documents: :func:`json.dumps` with
    ``sort_keys=True`` and the compact separators — the canonical-JSON
    spelling every member of this workspace that writes JSON for a
    comparison uses, and the spelling the trace beside these files gets
    (feature 173).  So two equal attributions built in different
    insertion orders stage identical bytes, and key order is never part
    of a stored document's identity.  List order is untouched, which is
    what makes the renderer safe for an array: the profile's positions
    are the axis, and ``sort_keys`` sorts an object's keys, never a
    list's entries.

    A value no renderer may emit — an unserializable object, a
    non-finite float, which ``allow_nan=False`` refuses because ``nan``
    is not JSON and a document a reader must round-trip cannot carry it
    — is refused here rather than staged as half a file, naming the file
    and the node it was being rendered for.
    """
    try:
        return json.dumps(
            body, sort_keys=True, separators=(",", ":"), allow_nan=False
        )
    except (TypeError, ValueError) as exc:
        raise ArtifactStoreError(
            f"the {filename!r} of node {node_id!r} of campaign "
            f"{campaign_id!r} must be renderable as JSON — {exc}; the "
            "document is one measurement of one node, and a value no "
            "JSON renderer may emit is not a fact about the node that "
            "can be stored beside it"
        ) from exc


# -- Reading the documents back -----------------------------------------------------


def _read_document(
    store: ArtifactStore,
    campaign_id: str,
    node_id: str,
    filename: str,
    *,
    expected: str,
) -> Any:
    """Read one of the two documents back, checked for its top-level shape.

    Shared by both readers because the bytes' discipline is one
    discipline: UTF-8, JSON, of the shape the artifact's own line in
    §9.2 fixes (an array for the profile, an object for the
    attribution), and free of Python's ``NaN``/``Infinity`` extension.
    A missing node or a missing file is the store's own refusal
    (:class:`~artifacts._errors.ArtifactNotFoundError`, naming which
    half is absent); everything else is a document this layer's writer
    did not produce, refused with
    :class:`~artifacts._errors.ArtifactStoreError` rather than answered
    as a stand-in.
    """
    raw = store.read(campaign_id, node_id, filename)
    try:
        parsed = json.loads(
            raw.decode("utf-8"), parse_constant=_refuse_constant
        )
    except (UnicodeDecodeError, ValueError) as exc:
        raise ArtifactStoreError(
            f"the {filename!r} of node {node_id!r} of campaign "
            f"{campaign_id!r} is not readable as JSON: {exc}; the "
            "document is one measurement of one node, and bytes no "
            "renderer of this member emitted are a file this writer "
            "never staged"
        ) from exc
    if expected == "array" and not isinstance(parsed, list):
        raise ArtifactStoreError(
            f"the {filename!r} of node {node_id!r} of campaign "
            f"{campaign_id!r} is not a JSON array — got "
            f"{type(parsed).__name__}; the decay profile is the "
            "information coefficient at each horizon, positionally, and "
            "anything else is a file this writer never staged"
        )
    if expected == "object" and not isinstance(parsed, dict):
        raise ArtifactStoreError(
            f"the {filename!r} of node {node_id!r} of campaign "
            f"{campaign_id!r} is not a JSON object — got "
            f"{type(parsed).__name__}; the regime attribution is the "
            "per-stratum split feature 82 renders, and anything else is "
            "a file this writer never staged"
        )
    return parsed


def _refuse_constant(name: str) -> Any:
    """Refuse Python's ``NaN``/``Infinity`` literals while parsing.

    :func:`json.loads` accepts three tokens JSON itself does not have —
    ``NaN``, ``Infinity``, ``-Infinity`` — and hands them back as
    floats, so a document carrying one would parse into a measurement
    this layer's writer could never have staged (``allow_nan=False``
    refuses them on the way in).  The evaluator's own reader refuses a
    non-finite entry for the same reason: a coefficient that is not a
    number is a number the artifact would trust and be wrong by.  The
    hook is called only for those three tokens, so the refusal is
    precise rather than a blanket rejection of the grammar's other
    extensions.
    """
    raise ValueError(
        f"{name} is Python's own extension to the JSON grammar, not JSON"
    )


def _is_persisted(
    store: ArtifactStore,
    campaign_id: str,
    node_id: str,
    filename: str,
) -> bool:
    """Whether a published node's directory holds ``filename``.

    Presence, shared by both invariant checks so the two answer the
    identical question about different names: the node's artifact is
    published *and* the file is in it.  Staged-but-uncommitted answers
    ``False``, which is the write path's invisibility rather than a
    missing document.
    """
    if not store.has_node(campaign_id, node_id):
        return False
    return filename in store.files(campaign_id, node_id)
