"""Feature 204's write path: a node's weights and dice, persisted and read back.

app_spec.xml feature 204: *System persists ``agent_ckpt_hash`` for self-hosted
weights plus ``agent_sampling`` recording temperature, top_p, thinking and
seed.*  This file holds the half of that sentence that is about the *row*: the
store calls that write the two columns, the states a node can be in when they
ask, and the answer each state gets.  The values themselves are
``test_ckpt.py``'s and ``test_sampling.py``'s.

**Three columns, two calls, and no core migration.**  Revision 0115 (feature
100's, already shipped) declares all three authoring-record columns, so this
feature adds none — what it adds is ``AgentModelPins.persist_weights``, which
fills the two 0115 left to it, and ``load_provenance``, which reads all three as
one answer.  The path to ``0115`` is the one the sentence states: it is the
migration that *already* carries ``agent_ckpt_hash`` and ``agent_sampling``, and
this member's job is to write through it.

**The row shapes reachable here are the schema's, not this suite's.**  On the
chain-built tree (``pinned_database``) 0115's bare ``NOT NULL`` landed on an
empty table and holds, so a node there always has all three columns written, and
the states this suite can drive are the retry, the two conflicts, the
hosted-API row and its digest counterpart.  The *write* branch needs a row whose
``agent_sampling`` is NULL, which only exists on a tree built outside the chain
— see ``weights_database`` in the conftest, which reaches it the way 0115's
docstring says the repair does (*"a backfill, not a spell"*) and says in as many
words that it builds nothing the schema's owner does not describe.

**The one decision this file exists to pin** is what a NULL in
``agent_ckpt_hash`` means, because it is the only place the two nullable columns
behave differently.  A NULL there is §9.1's *hosted-API weights*; a NULL in
``agent_sampling`` is *not recorded yet*.  Both are SQL NULL, so the column
cannot tell a reader which it is — and a store that read the hash's NULL as
"nothing here, go ahead and write" would let a checkpoint digest be written over
a row that records hosted weights, which is the direction the refusal's own
message calls the worst form of the mistake: it moves every score on the row
into another weight stratum while leaving the scores untouched.  The row's
sampling is what settles it, and the tests that drive that pair are marked as
the refusal tests they are.
"""

from __future__ import annotations

import sqlite3
from contextlib import closing

import pytest
from conftest import DEFAULT_AUTHOR, DEFAULT_CKPT_HASH, sqlite_path_of
from providers import (
    AGENT_CKPT_HASH_COLUMN,
    AGENT_SAMPLING_COLUMN,
    AgentModelPins,
    AgentSampling,
    AgentSamplingMalformedError,
    AgentWeights,
    CkptHashConflictError,
    CkptHashMalformedError,
    ModelPinError,
    NodeNotRecordedError,
    NodeProvenance,
    NodeProvenanceError,
    PinColumnError,
    RollingAliasError,
    SamplingConflictError,
)

#: §14.1's self-hosted checkpoint, as the suite's other modules spell it: a
#: digest of weights that were fetched rather than called for.
OTHER_DIGEST = "cd" * 32


# ── The row whose record was never written: this feature's backfill ───────────


def test_writing_the_weights_records_both_columns_in_one_call(
    weights_pins: AgentModelPins, plant_node, node_id, stored_weights, make_sampling
):
    # The sentence's two halves are one call, because they are one record: a
    # row holding a checkpoint hash and no sampling would describe weights whose
    # score came from a draw nobody can re-issue.
    plant_node(weights_pins.database_url, node_id, agent_sampling=None)
    assert stored_weights(weights_pins.database_url, node_id) == (None, None)

    answer = weights_pins.persist_weights(
        node_id, DEFAULT_CKPT_HASH, sampling=make_sampling(temperature=0.7)
    )

    assert isinstance(answer, AgentWeights)
    assert answer.recorded is True
    assert answer.ckpt_hash == DEFAULT_CKPT_HASH
    assert answer.self_hosted is True
    assert answer.agent_sampling == (
        '{"seed":0,"temperature":0.7,"thinking":false,"top_p":1.0}'
    )
    # And the row really holds it — read straight from the table, because the
    # question "did the store write?" is not one the store's own answer can
    # settle.
    assert stored_weights(weights_pins.database_url, node_id) == (
        DEFAULT_CKPT_HASH,
        '{"seed":0,"temperature":0.7,"thinking":false,"top_p":1.0}',
    )


def test_writing_hosted_weights_records_the_null_that_means_hosted(
    weights_pins: AgentModelPins, plant_node, node_id, stored_weights
):
    # The hosted case is a *record* rather than an omission: a provider's model
    # was called, there was no local checkpoint, and the sampling is the only
    # half of the pair that has a value.  The row is still fully recorded, which
    # is what the host/self-hosted split in any report reads.
    plant_node(weights_pins.database_url, node_id, agent_sampling=None)

    answer = weights_pins.persist_weights(node_id, sampling=AgentSampling(seed=7))

    assert answer.recorded is True
    assert answer.ckpt_hash is None
    assert answer.self_hosted is False
    assert stored_weights(weights_pins.database_url, node_id) == (
        None,
        '{"seed":7,"temperature":0.0,"thinking":false,"top_p":1.0}',
    )


def test_filling_only_the_missing_column_leaves_the_recorded_one_alone(
    weights_pins: AgentModelPins, plant_node, node_id, stored_weights, make_sampling
):
    # **The state one combined UPDATE gets wrong.**  The two columns are written
    # by two *separate* calls, so a row can hold the agreed digest and no
    # sampling — the split 203's own module docstring describes — and this is
    # the shape the write has to handle per column.  The sampling is what gets
    # filled; a statement guarded on the hash would write nothing here, and one
    # guarded on the sampling would silently skip re-writing a hash that is
    # already right (harmless in itself) while being the wrong statement for the
    # other direction.  Built through the store rather than by planting, because
    # the *store's* two-call sequence is what produces this row in practice.
    plant_node(weights_pins.database_url, node_id, agent_sampling=None)
    weights_pins.persist_weights(
        node_id, DEFAULT_CKPT_HASH, sampling=make_sampling(temperature=0.7)
    )
    # Now take the sampling back out, which is the row a call arriving with only
    # the weights would find on a tree where the dice were recorded separately.
    with closing(sqlite3.connect(sqlite_path_of(weights_pins.database_url))) as conn, conn:
        conn.execute(
            f"UPDATE node SET {AGENT_SAMPLING_COLUMN} = NULL WHERE id = ?", (node_id,)
        )
    assert stored_weights(weights_pins.database_url, node_id) == (DEFAULT_CKPT_HASH, None)

    answer = weights_pins.persist_weights(
        node_id, DEFAULT_CKPT_HASH, sampling=make_sampling(temperature=0.7)
    )

    # The hash was already correct and is *not* a conflict: the row's record is
    # unwritten — its sampling is NULL — so this call is the one writing it, and
    # the digest agrees with what it was told.
    assert answer.recorded is True
    assert stored_weights(weights_pins.database_url, node_id) == (
        DEFAULT_CKPT_HASH,
        '{"seed":0,"temperature":0.7,"thinking":false,"top_p":1.0}',
    )


def test_a_second_identical_call_writes_nothing_and_says_so(
    weights_pins: AgentModelPins, plant_node, node_id, stored_weights, make_sampling
):
    # Idempotence is the property §14 asks of every write these workers make: a
    # retry after an unknown outcome must be safe to make.  The answer says
    # which of the two happened — `recorded=False` is *found, not written* —
    # because a caller that needed to know whether it was the writer has no
    # other way to ask.
    plant_node(weights_pins.database_url, node_id, agent_sampling=None)
    ask = make_sampling(temperature=0.7)
    weights_pins.persist_weights(node_id, DEFAULT_CKPT_HASH, sampling=ask)

    answer = weights_pins.persist_weights(node_id, DEFAULT_CKPT_HASH, sampling=ask)

    assert answer.recorded is False
    assert answer.ckpt_hash == DEFAULT_CKPT_HASH
    assert stored_weights(weights_pins.database_url, node_id) == (
        DEFAULT_CKPT_HASH,
        ask.to_json(),
    )


# ── What the two columns refuse, and why it is two classes ────────────────────


def test_a_digest_offered_over_a_hosted_row_is_refused(
    pinned_database: str, plant_node, node_id
):
    # **The refusal this feature is load-bearing for, on the shipping tree.**
    # The row records hosted-API weights — its hash is NULL, which is a fact and
    # not an absence — and a call offers a checkpoint digest.  Those are
    # different weights, so this is the conflict, not a write: the column's NULL
    # cannot say so on its own, and it is the row's sampling that shows the
    # record was already written.
    plant_node(pinned_database, node_id)
    store = AgentModelPins(pinned_database)

    with pytest.raises(CkptHashConflictError) as refusal:
        store.persist_weights(node_id, DEFAULT_CKPT_HASH, sampling=AgentSampling())

    # The message has to name both sides, because "the row's hash is NULL" is
    # not a useful thing to tell someone: what they need is that the row records
    # a provider's weights and the call named a checkpoint's.
    assert "hosted-API weights" in str(refusal.value)
    assert DEFAULT_CKPT_HASH in str(refusal.value)


def test_hosted_weights_offered_over_a_digest_row_are_refused(
    pinned_database: str, plant_node, node_id
):
    # The mirror direction, and it needs its own test: the two are separate
    # branches and a fix that covered only the first would leave this one
    # writing over a pinned checkpoint.  A deployment that has genuinely moved
    # to hosted weights is a *different* node — the scores on this row were
    # produced by the checkpoint it names.
    plant_node(pinned_database, node_id, agent_ckpt_hash=DEFAULT_CKPT_HASH)

    with pytest.raises(CkptHashConflictError):
        AgentModelPins(pinned_database).persist_weights(
            node_id, sampling=AgentSampling()
        )


def test_two_different_digests_for_one_node_are_refused(
    pinned_database: str, plant_node, node_id
):
    plant_node(pinned_database, node_id, agent_ckpt_hash=DEFAULT_CKPT_HASH)

    with pytest.raises(CkptHashConflictError) as refusal:
        AgentModelPins(pinned_database).persist_weights(
            node_id, OTHER_DIGEST, sampling=AgentSampling()
        )
    assert DEFAULT_CKPT_HASH in str(refusal.value)
    assert OTHER_DIGEST in str(refusal.value)


def test_the_same_digest_on_a_recorded_row_is_an_idempotent_retry(
    pinned_database: str, plant_node, node_id
):
    # The pair of the test above: *disagree* is a refusal, *agree* is a retry,
    # and the two are one comparison apart.  A store that refused both would
    # make every retry fail; one that answered the disagreement as a retry would
    # let a node's weights move.
    plant_node(pinned_database, node_id, agent_ckpt_hash=DEFAULT_CKPT_HASH)

    answer = AgentModelPins(pinned_database).persist_weights(
        node_id, DEFAULT_CKPT_HASH, sampling=AgentSampling()
    )

    assert answer.recorded is False
    assert answer.self_hosted is True


@pytest.mark.parametrize(
    "moved",
    [
        {"temperature": 0.9},
        {"top_p": 0.5},
        {"thinking": True},
        {"seed": 99},
    ],
)
def test_settings_that_disagree_with_the_recorded_draw_are_refused(
    pinned_database: str, plant_node, node_id, make_sampling, moved
):
    # **One case per setting**, because the failure this catches is a comparison
    # written against fewer than four of them: the row then answers *already
    # recorded, and equal* for a different draw, and its score becomes
    # reproducible only by settings the row does not hold.  The knobs that move
    # most often are temperature and top_p, and a re-run that reuses a node id
    # across a config change is what lands here.
    plant_node(pinned_database, node_id, agent_sampling=make_sampling().to_json())

    with pytest.raises(SamplingConflictError) as refusal:
        AgentModelPins(pinned_database).persist_weights(
            node_id, sampling=make_sampling(**moved)
        )
    assert make_sampling().to_json() in str(refusal.value)
    assert make_sampling(**moved).to_json() in str(refusal.value)


def test_the_dice_are_reasoned_about_before_the_weights_are(
    weights_pins: AgentModelPins, plant_node, node_id, make_sampling
):
    # Ordering, and it is visible: the row holds a draw, and the call offers
    # both a different digest *and* different settings.  The hash is the column
    # a caller offering the wrong weights got wrong, and the sampling's
    # agreement is not worth reporting when the node in hand is the wrong one.
    # The mirror of feature 203's rule that the model is answered before the
    # weights.
    plant_node(
        weights_pins.database_url,
        node_id,
        agent_sampling=make_sampling().to_json(),
    )

    with pytest.raises(CkptHashConflictError):
        weights_pins.persist_weights(
            node_id, DEFAULT_CKPT_HASH, sampling=make_sampling(temperature=1.5)
        )


# ── The row that is not a row, and the row with no author ─────────────────────


def test_a_node_the_tree_does_not_hold_is_refused(
    weights_pins: AgentModelPins, node_id
):
    # A missing node is not a node with nothing recorded: the second is a row
    # that exists, and only the first says the tree has never heard of this id.
    # Neither of the two columns can be recorded for a node that is not there,
    # and this member does not own the ``node`` table to make one.
    with pytest.raises(NodeNotRecordedError):
        weights_pins.persist_weights(node_id, sampling=AgentSampling())


def test_a_row_with_no_authoring_model_is_refused(
    nullable_trio_database: str, plant_node, node_id
):
    # 0115's own words: a node with no model string is one the stratification
    # cannot place.  A row holding a hash and a sampling but no model would
    # *look* placeable — two of its three columns filled — while naming no model
    # at all, which is worse than an empty row because it reads as complete.
    # This is the state feature 203's backfill exists for.
    plant_node(nullable_trio_database, node_id, agent_model_id=None)

    with pytest.raises(NodeProvenanceError):
        AgentModelPins(nullable_trio_database).persist_weights(
            node_id, sampling=AgentSampling()
        )


def test_a_row_with_no_authoring_model_reads_as_no_provenance(
    nullable_trio_database: str, plant_node, node_id
):
    # The read side of the same row, and it is deliberately not the refusal:
    # a reader has no ask that can disagree with the row, so "nothing is
    # recorded here" is the honest answer and `None` is how it is spelled —
    # the same three-way distinction `load` draws between an absent node, an
    # unrecorded row and a read failure.
    plant_node(nullable_trio_database, node_id, agent_model_id=None)

    assert AgentModelPins(nullable_trio_database).load_provenance(node_id) is None


def test_a_row_whose_model_is_a_rolling_alias_is_refused_before_the_weights(
    nullable_trio_database: str, plant_node, node_id
):
    # The weights belonged to a model, and if the model is a rolling alias then
    # *which* model is not knowable — so the hash and the settings cannot be
    # reasoned about.  203's error, because it is 203's question that has no
    # answer; reporting a hash conflict here would answer the second question
    # where the first has none.
    plant_node(
        nullable_trio_database,
        node_id,
        agent_model_id="deepseek-v4-flash",
        agent_sampling=None,
    )

    with pytest.raises(RollingAliasError):
        AgentModelPins(nullable_trio_database).persist_weights(
            node_id, sampling=AgentSampling()
        )


def test_the_trio_columns_must_exist_and_the_refusal_names_the_revision(
    unpinned_database: str, node_id
):
    # The migration prerequisite, reported rather than discovered: a tree where
    # 0115 has not run has no authoring-record columns at all, and this call
    # cannot record into columns that are not there.
    with pytest.raises(PinColumnError):
        AgentModelPins(unpinned_database).persist_weights(
            node_id, sampling=AgentSampling()
        )


# ── Reading the three columns back as one answer ──────────────────────────────


def test_reading_provenance_answers_all_three_columns_at_once(
    pinned_database: str, plant_node, node_id, make_sampling
):
    # The record 0115's trio actually is, in the shape a stratification wants:
    # a caller asking *what produced this node* should not have to make three
    # calls a writer could interleave between.  The three properties render the
    # columns' own spellings, so no caller re-parses what the store parsed.
    sampling = make_sampling(temperature=0.4, top_p=0.9, thinking=True, seed=12345)
    plant_node(
        pinned_database,
        node_id,
        agent_ckpt_hash=DEFAULT_CKPT_HASH,
        agent_sampling=sampling.to_json(),
    )

    provenance = AgentModelPins(pinned_database).load_provenance(node_id)

    assert isinstance(provenance, NodeProvenance)
    assert provenance.node_id == node_id
    assert provenance.agent_model_id == DEFAULT_AUTHOR
    assert provenance.agent_ckpt_hash == DEFAULT_CKPT_HASH
    assert provenance.agent_sampling == sampling.to_json()
    assert provenance.sampling == sampling
    assert provenance.self_hosted is True
    # The read path writes nothing, so the flag that answers *did this call
    # write?* has no referent and says so rather than claiming either answer.
    assert provenance.recorded is None


def test_reading_provenance_of_a_hosted_node_is_not_the_unrecorded_state(
    pinned_database: str, plant_node, node_id
):
    # **The distinction the whole record turns on.**  A hosted node's hash is
    # NULL and its provenance is a full answer; a node whose row records nothing
    # answers `None` outright (tested above).  A caller can therefore always
    # tell "these weights are a provider's" from "nobody wrote this down", and
    # the two are different strata in any report that reads them.
    plant_node(pinned_database, node_id)

    provenance = AgentModelPins(pinned_database).load_provenance(node_id)

    assert provenance is not None
    assert provenance.ckpt_hash is None
    assert provenance.self_hosted is False
    assert provenance.sampling is not None


def test_reading_provenance_of_a_half_written_row_reports_the_missing_half(
    weights_pins: AgentModelPins, plant_node, node_id
):
    # A row whose sampling is NULL is a tree built outside the chain, where
    # 0115's constraint has not been applied or backfilled.  The read reports it
    # as the column holds it — `sampling is None` — rather than refusing, and
    # rather than inventing the settings: the null here means *not recorded*,
    # which is a different fact from the hash's null next to it, and the caller
    # that finds it is the one who has to run the backfill.
    plant_node(weights_pins.database_url, node_id, agent_sampling=None)

    provenance = weights_pins.load_provenance(node_id)

    assert provenance is not None
    assert provenance.sampling is None
    assert provenance.agent_sampling is None
    # The other null is still the hosted fact, and it is the same row.
    assert provenance.ckpt_hash is None
    assert provenance.self_hosted is False


def test_reading_provenance_of_a_node_the_tree_does_not_hold_is_refused(
    pinned_database: str, node_id
):
    with pytest.raises(NodeNotRecordedError):
        AgentModelPins(pinned_database).load_provenance(node_id)


def test_a_stored_document_that_is_not_four_settings_is_refused_with_the_node_named(
    pinned_database: str, plant_node, node_id
):
    # §14.1's corruption, caught at the read side — which is where it would
    # otherwise be laundered into a stratum.  The refusal names the row as well
    # as the value, because a sampling record is repaired *per node*: the draw
    # that produced that node's score is a fact only the run that made it holds.
    plant_node(pinned_database, node_id, agent_sampling='{"temperature": 0.7}')

    with pytest.raises(AgentSamplingMalformedError) as refusal:
        AgentModelPins(pinned_database).load_provenance(node_id)
    assert node_id in str(refusal.value)


def test_a_stored_hash_that_is_not_a_digest_is_refused_with_the_node_named(
    pinned_database: str, plant_node, node_id
):
    # The same corruption on the other column: a truncated digest is a value
    # that names no weights, and reporting it as a weight stratum would group
    # this node with others on no evidence.  Repaired per node, for the same
    # reason — the checkpoint the row's scores came from is not recoverable from
    # the row.
    plant_node(pinned_database, node_id, agent_ckpt_hash="ab" * 20)

    with pytest.raises(CkptHashMalformedError) as refusal:
        AgentModelPins(pinned_database).load_provenance(node_id)
    assert node_id in str(refusal.value)


def test_a_read_does_not_write_either_column(
    pinned_database: str, plant_node, node_id, stored_weights
):
    # Every other test here asks what the store *did*; this one asks what it did
    # not.  A read that quietly backfilled, or that normalized a stored value on
    # the way out, would make `load_provenance` a writer and put a row's contents
    # at the mercy of who read it first.
    plant_node(pinned_database, node_id, agent_ckpt_hash=f"  {DEFAULT_CKPT_HASH}\n".upper())
    before = stored_weights(pinned_database, node_id)

    AgentModelPins(pinned_database).load_provenance(node_id)

    assert stored_weights(pinned_database, node_id) == before


def test_a_read_refuses_a_malformed_node_id_the_same_way_a_write_does(
    weights_pins: AgentModelPins,
):
    # One addressing rule for both calls: an id that cannot join the primary key
    # names no node to read a record from, and it is this member's own error
    # rather than a subclass, because no subclass answers a question a caller
    # can act on here.
    with pytest.raises(ModelPinError):
        weights_pins.load_provenance("not-a-uuid")


def test_the_two_nulls_and_the_three_column_spellings_are_readable_together(
    weights_pins: AgentModelPins, plant_node, node_id, make_sampling
):
    # The end-to-end shape a report reads: write a self-hosted record on a
    # half-written row, then read the whole thing back and check that each of
    # the three columns is the value that was written — the digest as a digest,
    # the four settings as a document, and the model as the triple 203 stored.
    plant_node(weights_pins.database_url, node_id, agent_sampling=None)
    sampling = make_sampling(temperature=0.3, seed=2**40)

    weights_pins.persist_weights(node_id, DEFAULT_CKPT_HASH, sampling=sampling)
    provenance = weights_pins.load_provenance(node_id)

    assert provenance.agent_model_id == DEFAULT_AUTHOR
    assert provenance.agent_ckpt_hash == DEFAULT_CKPT_HASH
    assert provenance.sampling == sampling
    assert provenance.self_hosted is True
    assert provenance.recorded is None


def test_a_write_does_not_disturb_the_row_it_did_not_write(
    weights_pins: AgentModelPins, plant_node, node_id
):
    # The row's other columns — 0118's five and 0115's ``agent_model_id`` — are
    # not this feature's, and a write that rewrote the row rather than the two
    # columns would move the node in the tree.  Read raw, because the point is
    # what the *table* holds.
    plant_node(weights_pins.database_url, node_id, agent_sampling=None, depth=3)
    with closing(sqlite3.connect(sqlite_path_of(weights_pins.database_url))) as conn:
        before = conn.execute(
            "SELECT id, parent_id, campaign_id, theme_root, depth, agent_model_id "
            "FROM node WHERE id = ?",
            (node_id,),
        ).fetchone()

    weights_pins.persist_weights(node_id, DEFAULT_CKPT_HASH, sampling=AgentSampling())

    with closing(sqlite3.connect(sqlite_path_of(weights_pins.database_url))) as conn:
        after = conn.execute(
            "SELECT id, parent_id, campaign_id, theme_root, depth, agent_model_id "
            "FROM node WHERE id = ?",
            (node_id,),
        ).fetchone()
    assert after == before


# ── The two columns are not each other's ─────────────────────────────────────


def test_the_two_writes_touch_only_their_own_columns(
    weights_pins: AgentModelPins, plant_node, node_id, stored_weights, make_sampling
):
    # `persist` reads and writes ``agent_model_id`` and nothing else, and
    # ``persist_weights`` the other two — which is why a caller that needs both
    # makes both calls and a caller that needs one does not acquire the other's
    # state.  Driven in both directions, on the tree where the weights' write
    # branch is reachable: the row is planted with no dice, 203's call writes
    # its own column without touching the pair, and 204's call then writes the
    # pair without disturbing 203's column.
    plant_node(weights_pins.database_url, node_id, agent_sampling=None)
    store = weights_pins
    before = stored_weights(weights_pins.database_url, node_id)

    store.persist(node_id, DEFAULT_AUTHOR)
    # The mutual value is already what 203 would write, so the row's two
    # feature-204 columns are untouched by that call.
    assert stored_weights(weights_pins.database_url, node_id) == before

    store.persist_weights(node_id, DEFAULT_CKPT_HASH, sampling=make_sampling())
    assert stored_weights(weights_pins.database_url, node_id) == (
        DEFAULT_CKPT_HASH,
        make_sampling().to_json(),
    )
    # And 203's column is still the one it wrote — the pair did not move it.
    assert store.load(node_id) is not None


def test_a_malformed_ask_is_refused_before_anything_is_opened(
    pinned_database: str, node_id
):
    # Validation comes first for the reason 203's ``persist`` gives: a malformed
    # ask costs nothing, and a store that opened the database to discover the
    # problem would have taken a lock to refuse a string.  Both of this call's
    # two values are checked, so this test drives the hash and the sampling —
    # and it is run with the node absent on purpose, so that a store which
    # validated *after* reading the row would raise
    # :class:`~providers.NodeNotRecordedError` here instead.
    store = AgentModelPins(pinned_database)
    with pytest.raises(CkptHashMalformedError):
        store.persist_weights(node_id, "not-a-digest", sampling=AgentSampling())
    with pytest.raises(AgentSamplingMalformedError):
        store.persist_weights(node_id, DEFAULT_CKPT_HASH, sampling={"temperature": 0.7})


def test_the_answers_column_names_are_the_columns_themselves(
    weights_pins: AgentModelPins, plant_node, node_id, stored_weights, make_sampling
):
    # The record exposes the columns' own spellings under the columns' own
    # names, so a caller reading a report and a caller reading the schema use one
    # vocabulary.  Spelled here rather than derived, so a rename is a failing
    # test about the schema's names.
    assert AGENT_CKPT_HASH_COLUMN == "agent_ckpt_hash"
    assert AGENT_SAMPLING_COLUMN == "agent_sampling"
    plant_node(weights_pins.database_url, node_id, agent_sampling=None)
    answer = weights_pins.persist_weights(node_id, DEFAULT_CKPT_HASH, sampling=make_sampling())
    assert answer.agent_ckpt_hash == answer.ckpt_hash
