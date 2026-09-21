"""The decay profile and the regime attribution — §9.2's two JSON documents.

app_spec.xml, "Tree & Artifact Persistence", feature 172: *System
persists decay_profile and regime_attribution as JSON inside the node
artifact directory.*  These tests hold the layer to that sentence in the
places it can be read:

* **inside the node artifact directory** — each document stages through
  feature 169's write path and publishes by the node's one commit, so it
  sits inside the node's single directory beside every other §9.2 file,
  rolls back with everything else on a discard, and is replaced
  wholesale by a refresh;
* **as JSON** — canonical bytes (sorted keys, compact separators, no
  ``NaN``), so two equal documents stage identical bytes and key order
  is never part of a stored measurement's identity; and the profile's
  *positions* survive the render, which is what makes an array safe
  under a canonical renderer;
* **the two documents** — each is persisted, read and checked on its
  own: they come from two different measurement steps, so neither
  operation demands the other, and each invariant answers for one name;
* **the refusals** — a profile that is not a positional array of finite
  numbers or nulls, an attribution that is not an object of string keys,
  and a value no JSON renderer may emit all refuse *before the first
  staged byte*; the read side refuses bytes this member's writer cannot
  have produced and names what is wrong with them.

The *content* of the documents is the evaluator's: feature 81 owns the
horizon axis and feature 82 the strata vocabulary, and neither is
imported here (the workspace contract — no member imports another).
These tests therefore stage documents of the shapes those steps render
and assert only what this layer owns: the names, the two top-level
shapes, the canonical bytes, the read side and the refusals.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from artifacts import (
    COMPONENT_NAME,
    DECAY_PROFILE_FILENAME,
    REGIME_ATTRIBUTION_FILENAME,
    ArtifactKeyError,
    ArtifactNotFoundError,
    ArtifactStore,
    ArtifactStoreError,
    decay_profile,
    decay_profile_is_persisted,
    persist_decay_profile,
    persist_regime_attribution,
    regime_attribution,
    regime_attribution_is_persisted,
)

from app.module_loader import create_app

#: A decay profile in the shape feature 81's renderer answers: one entry
#: per horizon on the axis, ``None`` for a horizon the window was too
#: short to measure.  The axis itself is the evaluator's — these tests
#: never assert its length, only that the positions round-trip.
PROFILE = [0.071, 0.052, 0.031, None, None]

#: A regime attribution in the shape feature 82's renderer answers:
#: ``{stratum: {horizon: {...}}}`` plus ``unattributed_dates``.  The
#: inner vocabulary is the evaluator's and is staged, not asserted.
ATTRIBUTION = {
    "low-vol": {
        "1": {"dates": 41, "mean_post_cost_return": 0.0031},
        "5": {"dates": 41, "mean_post_cost_return": 0.0018},
    },
    "high-vol": {
        "1": {"dates": 19, "mean_post_cost_return": 0.0007},
    },
    "unattributed_dates": 3,
}


# -- The §9.2 names ---------------------------------------------------------------


def test_the_documents_names_are_the_layouts() -> None:
    # §9.2 spells the two lines "decay_profile.json" and
    # "regime_attribution.json"; the layer spells them once, and these
    # are those spellings — pinned so a rename on either side of the
    # seam shows up here rather than as a directory silently carrying
    # the wrong filename.
    assert DECAY_PROFILE_FILENAME == "decay_profile.json"
    assert REGIME_ATTRIBUTION_FILENAME == "regime_attribution.json"


# -- Inside: the documents ride feature 169's write path ---------------------------


def test_the_documents_stage_inside_the_nodes_staged_set(
    store: ArtifactStore, campaign_id: str, node_id: str
) -> None:
    # The write half: both documents join the node's staged set through
    # the store's own write path — no second plumbing — invisible to
    # every read until the commit publishes them.
    store.write(campaign_id, node_id, "signal_returns.parquet", b"returns")

    staged_profile = persist_decay_profile(
        store, campaign_id, node_id, PROFILE
    )
    staged_attribution = persist_regime_attribution(
        store, campaign_id, node_id, ATTRIBUTION
    )

    assert store.staged(campaign_id, node_id) == (
        "decay_profile.json",
        "regime_attribution.json",
        "signal_returns.parquet",
    )
    staged = store.staging_root / campaign_id / node_id
    assert staged_profile == staged / DECAY_PROFILE_FILENAME
    assert staged_attribution == staged / REGIME_ATTRIBUTION_FILENAME


def test_the_documents_publish_inside_the_node_artifact_directory(
    store: ArtifactStore,
    artifact_root: Path,
    campaign_id: str,
    node_id: str,
) -> None:
    # The feature's sentence, read end to end: §9.2's whole set staged,
    # one commit, and both documents sit *inside* the node's one
    # directory — keyed campaign then node, at the address the tree
    # store's ``artifact_uri`` names.
    store.write(campaign_id, node_id, "signal_returns.parquet", b"returns")
    store.write(campaign_id, node_id, "ic_series.parquet", b"ic")
    store.write(campaign_id, node_id, "turnover_series.parquet", b"turnover")
    persist_decay_profile(store, campaign_id, node_id, PROFILE)
    persist_regime_attribution(store, campaign_id, node_id, ATTRIBUTION)

    published = store.commit(campaign_id, node_id)

    assert published == artifact_root / campaign_id / node_id
    assert store.files(campaign_id, node_id) == (
        "decay_profile.json",
        "ic_series.parquet",
        "regime_attribution.json",
        "signal_returns.parquet",
        "turnover_series.parquet",
    )
    assert (published / DECAY_PROFILE_FILENAME).is_file()
    assert (published / REGIME_ATTRIBUTION_FILENAME).is_file()
    assert decay_profile_is_persisted(store, campaign_id, node_id)
    assert regime_attribution_is_persisted(store, campaign_id, node_id)


def test_the_layer_does_not_publish_by_itself(
    store: ArtifactStore, campaign_id: str, node_id: str
) -> None:
    # The commit, not the staging, is the publication — the same
    # discipline every other staged file rides.  A layer that published
    # on its own would be a second commit point beside feature 169's.
    persist_decay_profile(store, campaign_id, node_id, PROFILE)
    persist_regime_attribution(store, campaign_id, node_id, ATTRIBUTION)

    assert not store.has_node(campaign_id, node_id)

    store.commit(campaign_id, node_id)
    assert store.has_node(campaign_id, node_id)


def test_discard_rolls_both_documents_back_with_everything_else(
    store: ArtifactStore, campaign_id: str, node_id: str
) -> None:
    # An interrupted pipeline leaves nothing behind — not the derived
    # files, not the edge's two documents.  A profile that survived its
    # own run's rollback would be a measurement of a run that never
    # committed.
    store.write(campaign_id, node_id, "signal_returns.parquet", b"partial")
    persist_decay_profile(store, campaign_id, node_id, PROFILE)
    persist_regime_attribution(store, campaign_id, node_id, ATTRIBUTION)
    store.discard(campaign_id, node_id)

    assert store.staged(campaign_id, node_id) == ()
    assert not store.has_node(campaign_id, node_id)


def test_a_refresh_replaces_both_documents_wholesale(
    store: ArtifactStore, campaign_id: str, node_id: str
) -> None:
    # A re-persisted node carries the retry's documents, never a splice
    # of two runs: the refresh is feature 169's wholesale replace, and
    # both documents ride it like any other file — the retry's profile
    # can never be read beside the first attempt's attribution.
    persist_decay_profile(store, campaign_id, node_id, [0.1, 0.2])
    persist_regime_attribution(store, campaign_id, node_id, {"a": 1})
    store.commit(campaign_id, node_id)

    retry = [0.05, None, 0.02]
    persist_decay_profile(store, campaign_id, node_id, retry)
    store.commit(campaign_id, node_id)

    assert store.files(campaign_id, node_id) == (DECAY_PROFILE_FILENAME,)
    assert decay_profile(store, campaign_id, node_id) == retry
    assert not regime_attribution_is_persisted(store, campaign_id, node_id)


def test_re_staging_a_document_keeps_the_last_bytes(
    store: ArtifactStore, campaign_id: str, node_id: str
) -> None:
    # The staged set is a mapping, one entry per filename — re-staging a
    # document is a refresh of that one file, not a second document.
    persist_decay_profile(store, campaign_id, node_id, [0.1])
    persist_decay_profile(store, campaign_id, node_id, [0.2, 0.3])
    store.commit(campaign_id, node_id)

    assert decay_profile(store, campaign_id, node_id) == [0.2, 0.3]


def test_a_bad_key_refuses_before_anything_is_staged(
    store: ArtifactStore, campaign_id: str
) -> None:
    # The two-segment key is the layout, and it outranks both documents:
    # a malformed key refuses as a key failure with the value never
    # looked at, exactly as feature 169's own boundary behaves.
    with pytest.raises(ArtifactKeyError):
        persist_decay_profile(store, campaign_id, "../escape", PROFILE)
    with pytest.raises(ArtifactKeyError):
        persist_regime_attribution(
            store, campaign_id, "../escape", ATTRIBUTION
        )

    assert store.campaign_ids() == ()


# -- As JSON: canonical bytes ------------------------------------------------------


def test_the_documents_stage_as_canonical_json(
    store: ArtifactStore, campaign_id: str, node_id: str
) -> None:
    # One byte spelling of each document — sorted keys, compact
    # separators — so two equal documents stage equal bytes and key
    # order is never part of a stored measurement's identity.
    persist_decay_profile(store, campaign_id, node_id, PROFILE)
    persist_regime_attribution(store, campaign_id, node_id, ATTRIBUTION)
    store.commit(campaign_id, node_id)

    canonical = {"sort_keys": True, "separators": (",", ":")}
    assert store.read(campaign_id, node_id, DECAY_PROFILE_FILENAME) == (
        json.dumps(PROFILE, **canonical).encode()
    )
    assert store.read(campaign_id, node_id, REGIME_ATTRIBUTION_FILENAME) == (
        json.dumps(ATTRIBUTION, **canonical).encode()
    )


def test_two_equal_attributions_stage_identical_bytes(
    store: ArtifactStore, campaign_id: str, node_id: str, other_node_id: str
) -> None:
    # The canonical rendering is what makes a stored attribution
    # comparable: insertion order differs — including the order of the
    # strata themselves — the bytes do not.
    first = {"low-vol": {"1": 0.5}, "high-vol": {"1": 0.2}, "unattributed_dates": 0}
    second = {}
    for key in reversed(list(first)):
        second[key] = first[key]

    persist_regime_attribution(store, campaign_id, node_id, first)
    persist_regime_attribution(store, campaign_id, other_node_id, second)

    staged = store.staging_root / campaign_id
    assert (staged / node_id / REGIME_ATTRIBUTION_FILENAME).read_bytes() == (
        staged / other_node_id / REGIME_ATTRIBUTION_FILENAME
    ).read_bytes()


def test_the_profiles_positions_survive_the_canonical_render(
    store: ArtifactStore, campaign_id: str, node_id: str
) -> None:
    # ``sort_keys`` sorts an object's keys, never a list's entries — so
    # the positional spelling is safe under the canonical renderer, which
    # is the whole reason the profile is an array: entry i is the
    # coefficient at the axis's i-th horizon, and the entry-by-entry
    # comparison the live loop makes would be meaningless if the render
    # reordered it.
    profile = [0.9, 0.1, None, 0.5, 0.2]
    persist_decay_profile(store, campaign_id, node_id, profile)
    store.commit(campaign_id, node_id)

    assert decay_profile(store, campaign_id, node_id) == profile
    assert json.loads(
        store.read(campaign_id, node_id, DECAY_PROFILE_FILENAME)
    ) == profile


def test_an_un_measured_horizon_persists_as_json_null(
    store: ArtifactStore, campaign_id: str, node_id: str
) -> None:
    # "The window never spanned 20 bars" and "the signal has no edge at
    # 20 bars" are different findings, and only the second is a number a
    # promotion decision may be made on — so absence is carried as null
    # and never as a fabricated zero.
    persist_decay_profile(store, campaign_id, node_id, [0.4, None])
    store.commit(campaign_id, node_id)

    raw = store.read(campaign_id, node_id, DECAY_PROFILE_FILENAME)
    assert b"null" in raw
    assert decay_profile(store, campaign_id, node_id) == [0.4, None]


def test_non_ascii_text_round_trips(
    store: ArtifactStore, campaign_id: str, node_id: str
) -> None:
    # The documents carry the run's own text — a stratum name can be
    # any label the regime labeler produced — and a renderer that could
    # not carry it would not be one.
    attribution = {"σ-high": {"1": 0.5}, "unattributed_dates": 0}
    persist_regime_attribution(store, campaign_id, node_id, attribution)
    store.commit(campaign_id, node_id)

    assert regime_attribution(store, campaign_id, node_id) == attribution


def test_whole_numbers_round_trip_as_json_numbers(
    store: ArtifactStore, campaign_id: str, node_id: str
) -> None:
    # A coefficient that happens to be integral is still a number, and
    # the dates and counts inside an attribution are integers — none of
    # them is silently turned into text or dropped.
    persist_decay_profile(store, campaign_id, node_id, [1, 0, -0.5])
    persist_regime_attribution(store, campaign_id, node_id, ATTRIBUTION)
    store.commit(campaign_id, node_id)

    assert decay_profile(store, campaign_id, node_id) == [1, 0, -0.5]
    assert regime_attribution(store, campaign_id, node_id) == ATTRIBUTION


# -- The profile's refusals --------------------------------------------------------


def test_a_profile_that_is_a_mapping_is_refused_with_the_array_spelling(
    store: ArtifactStore, campaign_id: str, node_id: str
) -> None:
    # The axis is positional; a profile keyed by horizon would have to be
    # re-aligned by every reader, so it is refused with a pointer at the
    # array rather than quietly re-keyed.
    with pytest.raises(ArtifactStoreError, match="positional array"):
        persist_decay_profile(
            store, campaign_id, node_id, {"1": 0.5, "2": 0.4}
        )

    assert store.staged(campaign_id, node_id) == ()


def test_a_profile_that_is_text_is_refused_by_name(
    store: ArtifactStore, campaign_id: str, node_id: str
) -> None:
    # A str is a sequence of characters, and json would render it as a
    # JSON string — a document that is a string is not a profile that
    # measures anything, so it gets its own refusal rather than falling
    # into "not a sequence".
    for text in ("[0.1, 0.2]", "", "0.5"):
        with pytest.raises(ArtifactStoreError, match="JSON array"):
            persist_decay_profile(store, campaign_id, node_id, text)

    assert store.staged(campaign_id, node_id) == ()


def test_a_profile_of_another_type_is_refused(
    store: ArtifactStore, campaign_id: str, node_id: str
) -> None:
    for not_a_sequence in (None, 0.5, {"a": 1}.keys() | {"b"}):
        with pytest.raises(ArtifactStoreError, match="JSON array"):
            persist_decay_profile(store, campaign_id, node_id, not_a_sequence)

    assert store.staged(campaign_id, node_id) == ()


def test_an_empty_profile_is_refused(
    store: ArtifactStore, campaign_id: str, node_id: str
) -> None:
    # A profile with no positions measures no horizon at all.
    for empty in ([], ()):
        with pytest.raises(ArtifactStoreError, match="cannot be empty"):
            persist_decay_profile(store, campaign_id, node_id, empty)

    assert store.staged(campaign_id, node_id) == ()


def test_a_profile_entry_that_is_not_a_number_or_null_is_refused_by_position(
    store: ArtifactStore, campaign_id: str, node_id: str
) -> None:
    # The refusal names the position, because for a five-entry axis the
    # value alone does not say which horizon is wrong.
    with pytest.raises(ArtifactStoreError, match="position 1"):
        persist_decay_profile(
            store, campaign_id, node_id, [0.4, "0.3", 0.2]
        )

    assert store.staged(campaign_id, node_id) == ()


def test_a_boolean_profile_entry_is_refused(
    store: ArtifactStore, campaign_id: str, node_id: str
) -> None:
    # JSON has a boolean and a number, and a flag is not an information
    # coefficient — even though bool is an int in Python.
    with pytest.raises(ArtifactStoreError, match="position 0"):
        persist_decay_profile(store, campaign_id, node_id, [True, 0.3])

    assert store.staged(campaign_id, node_id) == ()


def test_a_non_finite_profile_entry_is_refused_by_position(
    store: ArtifactStore, campaign_id: str, node_id: str
) -> None:
    # nan and inf are not JSON; an un-measured horizon is spelled null.
    for not_finite in (float("nan"), float("inf"), float("-inf")):
        with pytest.raises(ArtifactStoreError, match="position 2"):
            persist_decay_profile(
                store, campaign_id, node_id, [0.1, 0.2, not_finite]
            )

    assert store.staged(campaign_id, node_id) == ()


# -- The attribution's refusals ----------------------------------------------------


def test_an_attribution_that_is_not_a_mapping_is_refused(
    store: ArtifactStore, campaign_id: str, node_id: str
) -> None:
    # regime_attribution.json holds a JSON object; a sequence or a
    # string is not one, and staging it would persist a document whose
    # second half cannot be read back.
    for not_an_object in (["low-vol"], "low-vol", None, 3.5):
        with pytest.raises(ArtifactStoreError, match="JSON object"):
            persist_regime_attribution(
                store, campaign_id, node_id, not_an_object
            )

    assert store.staged(campaign_id, node_id) == ()


def test_an_attribution_with_a_non_string_key_is_refused(
    store: ArtifactStore, campaign_id: str, node_id: str
) -> None:
    # json would silently stringify an int key; a stratum whose name
    # changed spelling between the caller and the file is one no reader
    # can join back to the regime it labels.
    with pytest.raises(ArtifactStoreError, match="keys are strings"):
        persist_regime_attribution(
            store, campaign_id, node_id, {1: {"1": 0.5}}
        )

    assert store.staged(campaign_id, node_id) == ()


def test_an_empty_attribution_is_refused(
    store: ArtifactStore, campaign_id: str, node_id: str
) -> None:
    # A real render of feature 82's record always carries at least the
    # unattributed_dates count, so an object with no keys is a document
    # no writer of this layer's step produced.
    with pytest.raises(ArtifactStoreError, match="cannot be empty"):
        persist_regime_attribution(store, campaign_id, node_id, {})

    assert store.staged(campaign_id, node_id) == ()


def test_an_attribution_value_json_cannot_render_is_refused(
    store: ArtifactStore, campaign_id: str, node_id: str
) -> None:
    # An unserializable object, and a non-finite float: ``nan`` is not
    # JSON, and a document a reader must round-trip cannot carry it.
    for unrenderable in (object(), float("nan")):
        with pytest.raises(ArtifactStoreError, match="renderable as JSON"):
            persist_regime_attribution(
                store,
                campaign_id,
                node_id,
                {"low-vol": {"1": unrenderable}},
            )

    assert store.staged(campaign_id, node_id) == ()


def test_a_refused_attribution_stages_neither_document(
    store: ArtifactStore, campaign_id: str, node_id: str
) -> None:
    # The refusals land before the first staged byte, so a refused
    # document leaves the staged set exactly as it was — including a
    # half staged by the other document's own call.
    persist_decay_profile(store, campaign_id, node_id, PROFILE)

    with pytest.raises(ArtifactStoreError):
        persist_regime_attribution(
            store, campaign_id, node_id, {1: "not string-keyed"}
        )

    assert store.staged(campaign_id, node_id) == (DECAY_PROFILE_FILENAME,)


# -- The read side -----------------------------------------------------------------


def test_the_readers_answer_the_documents_back(
    store: ArtifactStore, campaign_id: str, node_id: str
) -> None:
    persist_decay_profile(store, campaign_id, node_id, PROFILE)
    persist_regime_attribution(store, campaign_id, node_id, ATTRIBUTION)
    store.commit(campaign_id, node_id)

    assert decay_profile(store, campaign_id, node_id) == PROFILE
    assert regime_attribution(store, campaign_id, node_id) == ATTRIBUTION


def test_a_missing_node_refuses_naming_the_node(
    store: ArtifactStore, campaign_id: str, node_id: str
) -> None:
    # A node nothing was published for is a fact about the store, and
    # both readers report it the same way — as the missing node it is,
    # not as a missing file.
    for reader in (decay_profile, regime_attribution):
        with pytest.raises(ArtifactNotFoundError, match="no artifact"):
            reader(store, campaign_id, node_id)


def test_a_node_missing_one_document_refuses_naming_the_document(
    store: ArtifactStore, campaign_id: str, node_id: str
) -> None:
    # The two documents are produced at two different measurement steps,
    # so a node carrying one and not the other is a legitimate state —
    # and each reader names the file it could not find rather than
    # reporting the node as missing.
    store.write(campaign_id, node_id, DECAY_PROFILE_FILENAME, "[]")
    store.commit(campaign_id, node_id)

    with pytest.raises(
        ArtifactNotFoundError, match=REGIME_ATTRIBUTION_FILENAME
    ):
        regime_attribution(store, campaign_id, node_id)
    assert decay_profile(store, campaign_id, node_id) == []

    store.write(campaign_id, node_id, REGIME_ATTRIBUTION_FILENAME, "{}")
    store.commit(campaign_id, node_id)
    with pytest.raises(
        ArtifactNotFoundError, match="holds no 'decay_profile\\.json'"
    ):
        decay_profile(store, campaign_id, node_id)
    assert regime_attribution(store, campaign_id, node_id) == {}


def test_a_document_that_is_not_json_refuses(
    store: ArtifactStore, campaign_id: str, node_id: str
) -> None:
    # Bytes no renderer emitted are a file this member's write path
    # never staged; the read side refuses rather than guessing at a
    # stand-in measurement.
    store.write(campaign_id, node_id, DECAY_PROFILE_FILENAME, b"not json")
    store.write(
        campaign_id, node_id, REGIME_ATTRIBUTION_FILENAME, b"\xff\xfe"
    )
    store.commit(campaign_id, node_id)

    with pytest.raises(ArtifactStoreError, match="not readable as JSON"):
        decay_profile(store, campaign_id, node_id)
    with pytest.raises(ArtifactStoreError, match="not readable as JSON"):
        regime_attribution(store, campaign_id, node_id)


def test_a_profile_that_is_not_an_array_refuses(
    store: ArtifactStore, campaign_id: str, node_id: str
) -> None:
    store.write(campaign_id, node_id, DECAY_PROFILE_FILENAME, '{"1": 0.5}')
    store.commit(campaign_id, node_id)

    with pytest.raises(ArtifactStoreError, match="not a JSON array"):
        decay_profile(store, campaign_id, node_id)


def test_an_attribution_that_is_not_an_object_refuses(
    store: ArtifactStore, campaign_id: str, node_id: str
) -> None:
    store.write(
        campaign_id, node_id, REGIME_ATTRIBUTION_FILENAME, "[1, 2]"
    )
    store.commit(campaign_id, node_id)

    with pytest.raises(ArtifactStoreError, match="not a JSON object"):
        regime_attribution(store, campaign_id, node_id)


def test_a_document_carrying_pythons_nan_refuses(
    store: ArtifactStore, campaign_id: str, node_id: str
) -> None:
    # json.loads accepts NaN and Infinity even though JSON has neither,
    # and this layer's writer refuses them on the way in — so a document
    # holding one did not come from this writer, and answering it as a
    # measurement would be the fabricated number feature 81's own
    # refusal exists to prevent.
    store.write(
        campaign_id, node_id, DECAY_PROFILE_FILENAME, "[0.1, NaN, Infinity]"
    )
    store.write(
        campaign_id,
        node_id,
        REGIME_ATTRIBUTION_FILENAME,
        '{"low-vol": {"1": -Infinity}}',
    )
    store.commit(campaign_id, node_id)

    with pytest.raises(ArtifactStoreError, match="not readable as JSON"):
        decay_profile(store, campaign_id, node_id)
    with pytest.raises(ArtifactStoreError, match="not readable as JSON"):
        regime_attribution(store, campaign_id, node_id)


def test_a_read_refuses_a_filename_that_could_step_outside(
    store: ArtifactStore, campaign_id: str, node_id: str
) -> None:
    # The read side goes through the store's own key gate, so a
    # traversal dressed as a lookup finds no file to serve.
    store.write(campaign_id, node_id, DECAY_PROFILE_FILENAME, "[]")
    store.commit(campaign_id, node_id)

    with pytest.raises(ArtifactKeyError):
        store.read(campaign_id, node_id, "../decay_profile.json")


# -- The invariants, answered as facts ---------------------------------------------


def test_each_invariant_is_false_until_its_document_is_published(
    store: ArtifactStore, campaign_id: str, node_id: str
) -> None:
    # Staged-but-uncommitted is invisible by design — the discipline
    # feature 169 states — so each invariant is about published
    # directories only, and flips at the commit.
    assert not decay_profile_is_persisted(store, campaign_id, node_id)
    assert not regime_attribution_is_persisted(store, campaign_id, node_id)

    persist_decay_profile(store, campaign_id, node_id, PROFILE)
    assert not decay_profile_is_persisted(store, campaign_id, node_id)

    store.commit(campaign_id, node_id)
    assert decay_profile_is_persisted(store, campaign_id, node_id)
    assert not regime_attribution_is_persisted(store, campaign_id, node_id)


def test_the_two_invariants_do_not_answer_for_each_other(
    store: ArtifactStore, campaign_id: str, node_id: str
) -> None:
    # The two documents are independently readable — that is why they
    # are two operations rather than feature 173's pair — so asking one
    # question must not silently answer the other.  Each commit replaces
    # the directory wholesale, so the two land one at a time exactly as
    # a caller that reached one measurement step and not the other would
    # leave them.
    persist_decay_profile(store, campaign_id, node_id, PROFILE)
    store.commit(campaign_id, node_id)
    assert decay_profile_is_persisted(store, campaign_id, node_id)
    assert not regime_attribution_is_persisted(store, campaign_id, node_id)

    persist_regime_attribution(store, campaign_id, node_id, ATTRIBUTION)
    store.commit(campaign_id, node_id)
    assert not decay_profile_is_persisted(store, campaign_id, node_id)
    assert regime_attribution_is_persisted(store, campaign_id, node_id)


# -- Through the composed store ------------------------------------------------------


def test_feature_172_through_the_composed_store(
    artifact_root: Path, campaign_id: str, node_id: str
) -> None:
    # The feature through the path an assembled system takes: compose,
    # take the store the factory built, stage both documents, publish
    # them with the node's commit, and read both back.  The layer is
    # structural over the store — it speaks write/commit/read, never a
    # type check — so the composed copy serves it exactly as the
    # canonical import does.
    component = create_app().get(COMPONENT_NAME)

    persist_decay_profile(
        component, campaign_id, node_id, PROFILE  # type: ignore[arg-type]
    )
    persist_regime_attribution(
        component, campaign_id, node_id, ATTRIBUTION  # type: ignore[arg-type]
    )
    published = component.commit(campaign_id, node_id)  # type: ignore[attr-defined]

    assert published == artifact_root / campaign_id / node_id
    assert decay_profile(
        component, campaign_id, node_id  # type: ignore[arg-type]
    ) == PROFILE
    assert regime_attribution(
        component, campaign_id, node_id  # type: ignore[arg-type]
    ) == ATTRIBUTION
    assert decay_profile_is_persisted(
        component, campaign_id, node_id  # type: ignore[arg-type]
    )
    assert regime_attribution_is_persisted(
        component, campaign_id, node_id  # type: ignore[arg-type]
    )


def test_the_documents_are_exported_from_the_member() -> None:
    # The public API the category's later features and the app seat
    # reach.  A name that exists in ``_profiles`` and not here is a
    # spelling callers would have to reach into a private module for.
    import artifacts

    for name in (
        "DECAY_PROFILE_FILENAME",
        "REGIME_ATTRIBUTION_FILENAME",
        "decay_profile",
        "decay_profile_is_persisted",
        "persist_decay_profile",
        "persist_regime_attribution",
        "regime_attribution",
        "regime_attribution_is_persisted",
    ):
        assert name in artifacts.__all__, name
        assert hasattr(artifacts, name), name
