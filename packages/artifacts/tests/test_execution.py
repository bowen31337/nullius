"""The executed source plus its trace — the pair alongside every artifact.

app_spec.xml, "Tree & Artifact Persistence", feature 173: *System
persists the executed signal source plus an execution trace alongside
every stored artifact.*  These tests hold the layer to that sentence in
the four places it can be read:

* **alongside** — the pair stages through feature 169's write path and
  publishes by the node's one commit, so it sits in the node's single
  directory beside every other §9.2 file, rolls back with everything
  else on a discard, and is replaced wholesale by a refresh;
* **plus** — the pair is one operation that cannot stage a half: a
  source that is not module text, a trace that is not a JSON object, a
  value no renderer may emit, or a trace naming a node other than the
  one it is staged under all refuse *before the first staged byte*;
* **the read side** — the pair answers back by the same two keys, with
  refusals that name which half is missing, and
  :func:`~artifacts.execution_is_persisted` reports the invariant for a
  published node as a fact rather than an exception;
* **the identity tie** — :func:`~artifacts.source_code_hash` derives
  the sha256 §9.1's ``code_hash`` column carries from the very text
  staged as ``code.py``, so the tree row and the directory cannot
  disagree about which code a node ran.

The trace's *vocabulary* is feature 85's (the evaluator renders the
fingerprint); the tests stage a fingerprint of that shape but assert
only what this layer owns — the pairing, the canonical bytes, the
addressing agreement, the read side — never the evaluator's fields.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from artifacts import (
    COMPONENT_NAME,
    SOURCE_FILENAME,
    TRACE_FILENAME,
    ArtifactKeyError,
    ArtifactNotFoundError,
    ArtifactStore,
    ArtifactStoreError,
    canonical_code_hash,
    executed_source,
    execution_is_persisted,
    execution_trace,
    persist_execution,
    source_code_hash,
)

from app.module_loader import create_app

#: A signal source in the shape the sandbox executes — module text, and
#: not empty.  Every test that wants "a source" without a specific one
#: stages this.
SOURCE_TEXT = (
    "def signal(window):\n"
    "    close = window[\"close\"]\n"
    "    return close.pct_change()\n"
)


def _fingerprint(campaign_id: str, node_id: str) -> dict[str, object]:
    """A trace in the shape feature 85 renders, keyed to this node.

    The fields are the evaluator's vocabulary; what matters to these
    tests is only that the trace is a JSON object naming the node it is
    staged under, so a misfiled one has something to disagree with.
    """
    return {
        "node_id": node_id,
        "campaign_id": campaign_id,
        "snapshot_name": "sealed-2026-09-20T00:00:00Z",
        "evaluator_hash": "e" * 64,
        "cost_model": "venue=binance/version=1",
        "horizons": [1, 5, 22],
        "charges_budget": True,
        "steps_completed": [7, 8, 9, 11],
    }


def _persist_pair(
    store: ArtifactStore,
    campaign_id: str,
    node_id: str,
    *,
    source: str = SOURCE_TEXT,
    trace: dict[str, object] | None = None,
) -> tuple[Path, Path]:
    """Stage the pair for the node, with a fingerprint keyed to it."""
    return persist_execution(
        store,
        campaign_id,
        node_id,
        source=source,
        trace=(
            _fingerprint(campaign_id, node_id) if trace is None else trace
        ),
    )


# -- The §9.2 names ---------------------------------------------------------------


def test_the_pairs_names_are_the_layouts() -> None:
    # §9.2 spells the two lines "exec_trace.json" and "code.py"; the
    # layer spells them once, and these are those spellings — pinned so
    # a rename on either side of the seam shows up here rather than as
    # a directory silently carrying the wrong filename.
    assert SOURCE_FILENAME == "code.py"
    assert TRACE_FILENAME == "exec_trace.json"


# -- Alongside: the pair rides feature 169's write path ----------------------------


def test_the_pair_stages_alongside_the_nodes_artifact_files(
    store: ArtifactStore, campaign_id: str, node_id: str
) -> None:
    # The write half: both files join the node's staged set through the
    # store's own write path — no second plumbing — invisible to every
    # read until the commit publishes them.
    store.write(campaign_id, node_id, "signal_returns.parquet", b"returns")
    store.write(campaign_id, node_id, "decay_profile.json", b"[]")

    staged_source, staged_trace = _persist_pair(
        store, campaign_id, node_id
    )

    assert store.staged(campaign_id, node_id) == (
        "code.py",
        "decay_profile.json",
        "exec_trace.json",
        "signal_returns.parquet",
    )
    staged = store.staging_root / campaign_id / node_id
    assert staged_source == staged / "code.py"
    assert staged_trace == staged / "exec_trace.json"


def test_the_pair_publishes_alongside_every_stored_artifact_file(
    store: ArtifactStore, artifact_root: Path, campaign_id: str, node_id: str
) -> None:
    # The feature's sentence, read end to end: the node's published
    # directory holds the derived artifact files *and* the pair, because
    # the pair staged into the same set and the one commit published it.
    store.write(campaign_id, node_id, "signal_returns.parquet", b"returns")
    _persist_pair(store, campaign_id, node_id)

    published = store.commit(campaign_id, node_id)

    assert published == artifact_root / campaign_id / node_id
    assert store.files(campaign_id, node_id) == (
        "code.py",
        "exec_trace.json",
        "signal_returns.parquet",
    )
    assert store.read(campaign_id, node_id, "code.py") == (
        SOURCE_TEXT.encode()
    )
    assert execution_is_persisted(store, campaign_id, node_id)


def test_the_layer_does_not_publish_by_itself(
    store: ArtifactStore, campaign_id: str, node_id: str
) -> None:
    # The commit, not the pair's staging, is the publication — the same
    # discipline every other staged file rides.  A layer that published
    # on its own would be a second commit point beside feature 169's.
    _persist_pair(store, campaign_id, node_id)

    assert not store.has_node(campaign_id, node_id)

    store.commit(campaign_id, node_id)
    assert store.has_node(campaign_id, node_id)


def test_discard_rolls_the_pair_back_with_everything_else(
    store: ArtifactStore, campaign_id: str, node_id: str
) -> None:
    # An interrupted pipeline leaves nothing behind — not the derived
    # files, not the pair.  Provenance that survived its own run's
    # rollback would be a trace of an execution that never committed.
    store.write(campaign_id, node_id, "signal_returns.parquet", b"partial")
    _persist_pair(store, campaign_id, node_id)
    store.discard(campaign_id, node_id)

    assert store.staged(campaign_id, node_id) == ()
    assert not store.has_node(campaign_id, node_id)


def test_a_refresh_replaces_the_pair_wholesale(
    store: ArtifactStore, campaign_id: str, node_id: str
) -> None:
    # A re-persisted node carries the retry's pair, never a splice of
    # two runs: the refresh is feature 169's wholesale replace, and the
    # pair rides it like any other file — the retry's numbers can never
    # be read beside the first attempt's source.
    store.write(campaign_id, node_id, "signal_returns.parquet", b"v1")
    _persist_pair(store, campaign_id, node_id, source="# first attempt\n")
    store.commit(campaign_id, node_id)

    retry = "# the retry the tree row will point at\n"
    _persist_pair(store, campaign_id, node_id, source=retry)
    store.commit(campaign_id, node_id)

    assert store.files(campaign_id, node_id) == (
        "code.py",
        "exec_trace.json",
    )
    assert executed_source(store, campaign_id, node_id) == retry


def test_re_staging_the_pair_keeps_the_last_bytes(
    store: ArtifactStore, campaign_id: str, node_id: str
) -> None:
    # The staged set is a mapping, one entry per filename — re-staging
    # the pair is a refresh of both files, not a second pair.
    _persist_pair(store, campaign_id, node_id, source="# v1\n")
    _persist_pair(store, campaign_id, node_id, source="# v2\n")
    store.commit(campaign_id, node_id)

    assert executed_source(store, campaign_id, node_id) == "# v2\n"


# -- Plus: one operation, both halves ----------------------------------------------


def test_a_source_of_bytes_is_refused_with_a_pointer_to_decode(
    store: ArtifactStore, campaign_id: str, node_id: str
) -> None:
    # The source is module text; bytes passed through would untie the
    # file's bytes from the sha256 the tree row carries.  Nothing is
    # staged — not the trace either, because the pair refused as one.
    with pytest.raises(ArtifactStoreError, match="module text"):
        _persist_pair(store, campaign_id, node_id, source=b"# code")  # type: ignore[arg-type]

    assert store.staged(campaign_id, node_id) == ()


def test_a_source_of_another_type_is_refused(
    store: ArtifactStore, campaign_id: str, node_id: str
) -> None:
    with pytest.raises(ArtifactStoreError, match="module text"):
        _persist_pair(store, campaign_id, node_id, source=3.5)  # type: ignore[arg-type]

    assert store.staged(campaign_id, node_id) == ()


def test_an_empty_source_is_refused(
    store: ArtifactStore, campaign_id: str, node_id: str
) -> None:
    # Source with no characters is no execution at all — there is no
    # module for the trace to be the trace of.
    for empty in ("", "   \n"):
        with pytest.raises(ArtifactStoreError, match="cannot be empty"):
            _persist_pair(store, campaign_id, node_id, source=empty)

    assert store.staged(campaign_id, node_id) == ()


def test_a_trace_that_is_not_a_mapping_is_refused(
    store: ArtifactStore, campaign_id: str, node_id: str
) -> None:
    # exec_trace.json holds a JSON object; a sequence or a string is not
    # one, and staging it beside the source would persist a pair whose
    # second half cannot be read back.
    for not_an_object in (["node_id", node_id], "steps: [7]", None):
        with pytest.raises(ArtifactStoreError, match="JSON object"):
            persist_execution(
                store,
                campaign_id,
                node_id,
                source=SOURCE_TEXT,
                trace=not_an_object,  # type: ignore[arg-type]
            )

    assert store.staged(campaign_id, node_id) == ()


def test_a_trace_with_a_non_string_key_is_refused(
    store: ArtifactStore, campaign_id: str, node_id: str
) -> None:
    # json would silently stringify an int key; a fingerprint whose
    # keys changed spelling between the caller and the file is one
    # nothing can compare against.
    with pytest.raises(ArtifactStoreError, match="keys are strings"):
        _persist_pair(
            store,
            campaign_id,
            node_id,
            trace={1: "one"},  # type: ignore[dict-item]
        )

    assert store.staged(campaign_id, node_id) == ()


def test_a_trace_value_json_cannot_render_is_refused(
    store: ArtifactStore, campaign_id: str, node_id: str
) -> None:
    # An unserializable object, and a non-finite float: ``nan`` is not
    # JSON, and a fingerprint a parser must round-trip cannot carry it.
    for unrenderable in (object(), float("nan")):
        with pytest.raises(ArtifactStoreError, match="renderable as JSON"):
            _persist_pair(
                store,
                campaign_id,
                node_id,
                trace={"entry": unrenderable},
            )

    assert store.staged(campaign_id, node_id) == ()


def test_a_trace_naming_a_different_node_is_refused(
    store: ArtifactStore, campaign_id: str, node_id: str, other_node_id: str
) -> None:
    # The misfiling the pair exists to prevent: a trace filed under a
    # node it does not fingerprint.  Every later reader joins the
    # directory by these keys and would answer "whose run was this?"
    # with the wrong name — so the staging refuses, as one pair.
    misfiled = _fingerprint(campaign_id, other_node_id)
    with pytest.raises(ArtifactStoreError, match="staged under"):
        _persist_pair(store, campaign_id, node_id, trace=misfiled)

    assert store.staged(campaign_id, node_id) == ()


def test_a_trace_naming_a_different_campaign_is_refused(
    store: ArtifactStore, campaign_id: str, node_id: str, other_campaign_id: str
) -> None:
    misfiled = _fingerprint(other_campaign_id, node_id)
    with pytest.raises(ArtifactStoreError, match="staged under"):
        _persist_pair(store, campaign_id, node_id, trace=misfiled)

    assert store.staged(campaign_id, node_id) == ()


def test_a_trace_naming_the_node_it_is_staged_under_is_accepted(
    store: ArtifactStore, campaign_id: str, node_id: str
) -> None:
    # The evaluator's fingerprint carries both keys; agreeing with the
    # directory's own keys is not a misfiling but the self-description
    # the trace is supposed to carry.
    _persist_pair(store, campaign_id, node_id)
    store.commit(campaign_id, node_id)

    read_back = execution_trace(store, campaign_id, node_id)
    assert read_back["node_id"] == node_id
    assert read_back["campaign_id"] == campaign_id


def test_a_trace_carrying_neither_address_key_is_accepted(
    store: ArtifactStore, campaign_id: str, node_id: str
) -> None:
    # The vocabulary is the evaluator's: a trace that names no node is
    # not a misfiling, it is a spelling this layer does not own and so
    # does not demand — refusing it would be reaching across the seam.
    _persist_pair(store, campaign_id, node_id, trace={"steps": [7]})
    store.commit(campaign_id, node_id)

    assert execution_trace(store, campaign_id, node_id) == {"steps": [7]}


def test_a_bad_key_refuses_before_anything_is_staged(
    store: ArtifactStore, campaign_id: str
) -> None:
    # The two-segment key is the layout, and it outranks the pair: a
    # malformed key refuses as a key failure with the payload never
    # looked at, exactly as feature 169's own boundary behaves.
    with pytest.raises(ArtifactKeyError):
        persist_execution(
            store,
            campaign_id,
            "../escape",
            source=SOURCE_TEXT,
            trace=_fingerprint(campaign_id, "n1"),
        )

    assert store.campaign_ids() == ()


# -- Canonical bytes ---------------------------------------------------------------


def test_the_trace_stages_as_canonical_json(
    store: ArtifactStore, campaign_id: str, node_id: str
) -> None:
    # One byte spelling of a trace — sorted keys, compact separators —
    # so two equal traces stage equal bytes and key order is never part
    # of a trace's identity.
    trace = _fingerprint(campaign_id, node_id)
    _persist_pair(store, campaign_id, node_id, trace=trace)
    store.commit(campaign_id, node_id)

    assert store.read(campaign_id, node_id, TRACE_FILENAME) == (
        json.dumps(trace, sort_keys=True, separators=(",", ":")).encode()
    )


def test_two_equal_traces_stage_identical_bytes(
    store: ArtifactStore, campaign_id: str, node_id: str, other_node_id: str
) -> None:
    # The canonical rendering is what makes a stored trace comparable:
    # insertion order differs, the bytes do not.  The traces carry no
    # address keys so both name — and equal — the value they stage.
    first = {"horizons": [1, 5, 22], "charges_budget": True, "λ": 0.5}
    second = dict(reversed(list(first.items())))
    _persist_pair(store, campaign_id, node_id, trace=first)
    _persist_pair(store, campaign_id, other_node_id, trace=second)

    staged = store.staging_root / campaign_id
    assert (staged / node_id / TRACE_FILENAME).read_bytes() == (
        staged / other_node_id / TRACE_FILENAME
    ).read_bytes()
    assert (staged / node_id / SOURCE_FILENAME).read_bytes() == (
        staged / other_node_id / SOURCE_FILENAME
    ).read_bytes()


def test_non_ascii_text_round_trips(
    store: ArtifactStore, campaign_id: str, node_id: str
) -> None:
    # The source is encoded UTF-8 and the trace's non-ASCII values
    # survive the canonical rendering — the pair is the record of the
    # run, and a renderer that could not carry the run's own text
    # would not be one.
    source = "LAMBDA = 0.5  # λ, the shrinkage the run used\n"
    trace = {"note": "ünïcode", "λ": 0.5}
    _persist_pair(store, campaign_id, node_id, source=source, trace=trace)
    store.commit(campaign_id, node_id)

    assert executed_source(store, campaign_id, node_id) == source
    assert execution_trace(store, campaign_id, node_id) == trace


# -- The read side -----------------------------------------------------------------


def test_executed_source_returns_the_module_text(
    store: ArtifactStore, campaign_id: str, node_id: str
) -> None:
    _persist_pair(store, campaign_id, node_id)
    store.commit(campaign_id, node_id)

    assert executed_source(store, campaign_id, node_id) == SOURCE_TEXT


def test_a_missing_node_refuses_naming_the_node(
    store: ArtifactStore, campaign_id: str, node_id: str
) -> None:
    # A node nothing was published for is a fact about the store, and
    # both halves of the pair report it the same way — as the missing
    # node it is, not as a missing file.
    for reader in (executed_source, execution_trace):
        with pytest.raises(ArtifactNotFoundError, match="no artifact"):
            reader(store, campaign_id, node_id)


def test_a_node_missing_one_half_refuses_naming_the_half(
    store: ArtifactStore, campaign_id: str, node_id: str
) -> None:
    # The half pair, found and named: a directory holding only code.py
    # refuses the trace read by naming exec_trace.json, and one holding
    # only the trace refuses the source read by naming code.py — the
    # two states a hand-staged write can leave, told apart by which
    # half is absent.
    store.write(campaign_id, node_id, "code.py", SOURCE_TEXT)
    store.commit(campaign_id, node_id)
    with pytest.raises(ArtifactNotFoundError, match=TRACE_FILENAME):
        execution_trace(store, campaign_id, node_id)
    assert executed_source(store, campaign_id, node_id) == SOURCE_TEXT

    store.write(campaign_id, node_id, "exec_trace.json", "{}")
    store.commit(campaign_id, node_id)
    with pytest.raises(
        ArtifactNotFoundError, match="holds no 'code\\.py'"
    ):
        executed_source(store, campaign_id, node_id)
    assert execution_trace(store, campaign_id, node_id) == {}


def test_a_trace_that_is_not_json_refuses(
    store: ArtifactStore, campaign_id: str, node_id: str
) -> None:
    # Bytes no renderer emitted are a file this member's write path
    # never staged; the read side refuses rather than guessing at a
    # stand-in fingerprint.
    store.write(campaign_id, node_id, "exec_trace.json", b"not json")
    store.commit(campaign_id, node_id)

    with pytest.raises(ArtifactStoreError, match="not readable as JSON"):
        execution_trace(store, campaign_id, node_id)


def test_a_trace_that_is_not_an_object_refuses(
    store: ArtifactStore, campaign_id: str, node_id: str
) -> None:
    store.write(campaign_id, node_id, "exec_trace.json", "[1, 2]")
    store.commit(campaign_id, node_id)

    with pytest.raises(ArtifactStoreError, match="not a JSON object"):
        execution_trace(store, campaign_id, node_id)


def test_source_bytes_that_are_not_utf8_refuse(
    store: ArtifactStore, campaign_id: str, node_id: str
) -> None:
    # The source's hash is the node's identity in the tree store; bytes
    # that cannot be decoded cannot be hashed into it, so the read
    # refuses rather than answering a lossy guess.
    store.write(campaign_id, node_id, "code.py", b"\xff\xfe\x00s")
    store.commit(campaign_id, node_id)

    with pytest.raises(ArtifactStoreError, match="not UTF-8"):
        executed_source(store, campaign_id, node_id)


# -- The invariant, answered as a fact ----------------------------------------------


def test_the_invariant_is_false_until_the_pair_is_published(
    store: ArtifactStore, campaign_id: str, node_id: str
) -> None:
    # Staged-but-uncommitted is invisible by design — the discipline
    # feature 169 states — so the invariant is about published
    # directories only, and flips at the commit.
    assert not execution_is_persisted(store, campaign_id, node_id)

    _persist_pair(store, campaign_id, node_id)
    assert not execution_is_persisted(store, campaign_id, node_id)

    store.commit(campaign_id, node_id)
    assert execution_is_persisted(store, campaign_id, node_id)


def test_the_invariant_catches_the_half_pair(
    store: ArtifactStore, campaign_id: str, node_id: str
) -> None:
    # What the check exists to find: a published directory holding one
    # of the two names — the state a hand-staged write, or a writer
    # that ignored the pair's operation, leaves behind.  Each commit
    # replaces the directory wholesale, so the two halves land one at
    # a time exactly as a hand-staging caller would leave them.
    store.write(campaign_id, node_id, "code.py", SOURCE_TEXT)
    store.commit(campaign_id, node_id)
    assert not execution_is_persisted(store, campaign_id, node_id)

    store.write(campaign_id, node_id, "exec_trace.json", "{}")
    store.commit(campaign_id, node_id)
    assert not execution_is_persisted(store, campaign_id, node_id)

    _persist_pair(store, campaign_id, node_id)
    store.commit(campaign_id, node_id)
    assert execution_is_persisted(store, campaign_id, node_id)


# -- The identity tie --------------------------------------------------------------


def test_source_code_hash_is_the_sha256_of_the_persisted_source(
    store: ArtifactStore, campaign_id: str, node_id: str
) -> None:
    # The layer that persists code.py is the one place the hash of the
    # bytes actually persisted can be taken: the tree row's code_hash
    # and the directory's code.py are one value, read off one file.
    _persist_pair(store, campaign_id, node_id)
    store.commit(campaign_id, node_id)

    persisted = store.read(campaign_id, node_id, SOURCE_FILENAME)
    assert source_code_hash(SOURCE_TEXT) == (
        hashlib.sha256(persisted).hexdigest()
    )


def test_source_code_hash_is_canonical() -> None:
    # §9.1 types the column CHAR(64); the derivation answers exactly
    # what feature 179's canonical spelling accepts, and two sources
    # are two identities — the whole of the dedup gate's premise.
    digest = source_code_hash(SOURCE_TEXT)

    assert canonical_code_hash(digest) == digest
    assert len(digest) == 64
    assert digest == source_code_hash(SOURCE_TEXT)
    assert digest != source_code_hash(SOURCE_TEXT + "# a character more\n")


def test_source_code_hash_refuses_what_persist_refuses() -> None:
    # A hash of a value the write path would refuse is the identity of
    # a code.py that will never exist — so the two validations agree.
    with pytest.raises(ArtifactStoreError, match="module text"):
        source_code_hash(b"# bytes")  # type: ignore[arg-type]
    with pytest.raises(ArtifactStoreError, match="cannot be empty"):
        source_code_hash("")


# -- Through the composed store ------------------------------------------------------


def test_feature_173_through_the_composed_store(
    artifact_root: Path, campaign_id: str, node_id: str
) -> None:
    # The feature through the path an assembled system takes: compose,
    # take the store the factory built, stage the pair, publish it with
    # the node's commit, and read both halves back.  The layer is
    # structural over the store — it speaks write/commit/read, never a
    # type check — so the composed copy serves it exactly as the
    # canonical import does.
    component = create_app().get(COMPONENT_NAME)

    trace = _fingerprint(campaign_id, node_id)
    persist_execution(
        component,  # type: ignore[arg-type]
        campaign_id,
        node_id,
        source=SOURCE_TEXT,
        trace=trace,
    )
    published = component.commit(campaign_id, node_id)  # type: ignore[attr-defined]

    assert published == artifact_root / campaign_id / node_id
    assert execution_is_persisted(
        component, campaign_id, node_id  # type: ignore[arg-type]
    )
    assert executed_source(
        component, campaign_id, node_id  # type: ignore[arg-type]
    ) == SOURCE_TEXT
    assert execution_trace(
        component, campaign_id, node_id  # type: ignore[arg-type]
    ) == trace
