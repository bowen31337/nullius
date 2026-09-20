"""The row layer of feature 86: the record as a validated, frozen value.

``TrialLedgerRecord`` is the one shape a trial row takes — at the write
(the append builds its return value through this constructor) and at the
read (rows are rebuilt through it, which is how a malformed row on disk
is refused rather than served).  These tests pin the constructor's
contract: identities are UUIDs and are canonicalised, the stamp is
aware-UTC and a naive instant is refused, the sequence number is a
positive integer the ledger could have assigned, the outcome is one of
the four a trial can end in (the vocabulary's own refusal cases live in
test_outcome.py), the epoch is a name carried in its own spelling or
``None`` for a row that predates the stamp (the write's required-epoch
refusal is test_epoch.py's subject), the provenance triple is carried in
canonical lowercase hex or ``None`` for a row that predates the stamp
(the write's required-triple refusal is test_provenance.py's subject),
and the value is frozen once built.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import uuid
from datetime import timezone

import pytest

from ledger import TrialLedgerRecord, TrialRecordError, utc_now

NODE = uuid.UUID("00000000-0000-4000-8000-000000000001")
CAMPAIGN = "00000000-0000-4000-8000-0000000000c9"
CHARGES_BUDGET = True


def _record(**overrides: object) -> TrialLedgerRecord:
    """A well-formed record, with any field overridden by the test."""
    fields: dict[str, object] = {
        "seq": 1,
        "ts": dt.datetime(2026, 9, 20, 5, 0, 0, tzinfo=timezone.utc),
        "node_id": NODE,
        "campaign_id": CAMPAIGN,
        "outcome": "ok",
        "charges_budget": True,
    }
    fields.update(overrides)
    return TrialLedgerRecord(**fields)  # type: ignore[arg-type]


# -- Identities ------------------------------------------------------------


def test_a_uuid_object_is_canonicalised_to_hyphenated_lowercase() -> None:
    record = _record()
    assert record.node_id == "00000000-0000-4000-8000-000000000001"


def test_uppercase_text_is_normalised_to_the_canonical_spelling() -> None:
    record = _record(node_id="00000000-0000-4000-8000-000000000001".upper())
    assert record.node_id == "00000000-0000-4000-8000-000000000001"


def test_a_hex_blob_without_hyphens_is_still_the_same_uuid() -> None:
    # uuid.UUID parses the unhyphenated spelling; the record stores the one
    # canonical form so the row joins however the caller came by the value.
    record = _record(campaign_id="000000000000400080000000000000C9")
    assert record.campaign_id == CAMPAIGN


@pytest.mark.parametrize("bad", ["not-a-uuid", "", "0000", "uuid:1234"])
def test_text_that_is_not_a_uuid_is_refused(bad: str) -> None:
    with pytest.raises(TrialRecordError, match="node_id must be a UUID"):
        _record(node_id=bad)


def test_a_non_string_non_uuid_identity_is_refused_by_type() -> None:
    with pytest.raises(TrialRecordError, match="must be a UUID or its text"):
        _record(campaign_id=12345)


# -- The stamp -------------------------------------------------------------


def test_a_naive_datetime_is_refused() -> None:
    # A ledger stamp is compared and ranged against other instants; a naive
    # one would detonate as a TypeError far from the write that omitted the
    # offset, so it is refused here where the omission can be explained.
    with pytest.raises(TrialRecordError, match="timezone-aware"):
        _record(ts=dt.datetime(2026, 9, 20, 5, 0, 0))


def test_an_aware_instant_in_another_offset_is_normalised_to_utc() -> None:
    stamp = dt.datetime(
        2026, 9, 20, 15, 30, 0, tzinfo=dt.timezone(dt.timedelta(hours=10))
    )
    record = _record(ts=stamp)
    assert record.ts == dt.datetime(2026, 9, 20, 5, 30, 0, tzinfo=timezone.utc)


def test_the_iso_text_the_table_stores_is_accepted_back() -> None:
    # The read path rebuilds rows from the table's TEXT column; the exact
    # string a write stored must revalidate through the same constructor.
    record = _record(ts="2026-09-20T05:00:00+00:00")
    assert record.ts == dt.datetime(2026, 9, 20, 5, 0, 0, tzinfo=timezone.utc)


def test_unparseable_stamp_text_is_refused() -> None:
    with pytest.raises(TrialRecordError, match="ISO-8601"):
        _record(ts="not a timestamp")


def test_a_non_datetime_stamp_is_refused_by_type() -> None:
    with pytest.raises(TrialRecordError, match="timezone-aware datetime"):
        _record(ts=17)


def test_the_default_clock_is_aware_utc_at_second_resolution() -> None:
    stamp = utc_now()
    assert stamp.tzinfo is not None
    assert stamp.utcoffset() == dt.timedelta(0)
    # Microseconds are dropped, not rounded: the stamp is never after the
    # instant observed, and debits that land in the same second carry the
    # same second.
    assert stamp.microsecond == 0


# -- The sequence number ---------------------------------------------------


@pytest.mark.parametrize("bad", [0, -1, "1", 1.0, True])
def test_a_sequence_the_ledger_could_not_have_assigned_is_refused(
    bad: object,
) -> None:
    # AUTOINCREMENT counts from 1; bool is an int subclass whose True would
    # otherwise slip through as 1; text and floats are not sequence numbers
    # and must not be coerced into rows the ledger never appended.
    with pytest.raises(TrialRecordError, match="seq"):
        _record(seq=bad)


def test_the_first_sequence_number_is_one() -> None:
    # The count starts at 1 — the fact the store's first append relies on.
    assert _record(seq=1).seq == 1


# -- The value -------------------------------------------------------------


def test_a_record_is_frozen() -> None:
    # Append-only accounting: a persisted charge is a fact, and editing one
    # in place would rewrite the account rather than superseding it.
    record = _record()
    with pytest.raises(dataclasses.FrozenInstanceError):
        record.seq = 2  # type: ignore[misc]


def test_the_column_tuple_is_in_table_order() -> None:
    # The record's column tuple is the table's declaration order: after
    # feature 88's epoch comes feature 87's provenance triple, which
    # closes the row — the reader that unpacks it cannot mistake a
    # holdout's name or a provenance hash for an identity, a stamp or the
    # unit.  ``None`` here is the read's spelling for a row that predates
    # the stamps; the write's required-epoch and required-triple
    # refusals are the store's and the endpoint's (test_epoch.py and
    # test_provenance.py pin both).
    record = _record(seq=7)
    assert record.row() == (
        7,
        "2026-09-20T05:00:00+00:00",
        "00000000-0000-4000-8000-000000000001",
        CAMPAIGN,
        "ok",
        1,
        1.0,
        None,
        None,
        None,
        None,
    )


# -- The epoch ---------------------------------------------------------------


def test_the_epoch_is_carried_in_its_own_spelling() -> None:
    # The epoch namespace is the sealing process's — this layer holds the
    # name to being a name, it coins and canonicalises none of it — so
    # what the caller named is what the record carries, what the row
    # stores and what epoch_ledger keys on.
    assert _record(epoch_id="epoch-7").epoch_id == "epoch-7"
    assert _record(epoch_id="holdout-2026-09").epoch_id == "holdout-2026-09"


def test_none_is_the_pre_stamp_reads_spelling() -> None:
    # The record is also the read, and a row written before the stamp
    # landed — on a table the legacy upgrade brought forward — honestly
    # names no epoch.  ``None`` is that statement; it is refused at the
    # write seams, never here.
    assert _record(epoch_id=None).epoch_id is None


@pytest.mark.parametrize("bad", ["", "   ", "\t", 7, True, [], object()])
def test_an_epoch_that_names_no_epoch_is_refused(bad: object) -> None:
    # Blank is a name no sealing process coined, and a non-string is not
    # a name at all.  The read revalidates through this same check, which
    # is how a row whose epoch wandered into a value that names no epoch
    # is refused rather than served.
    with pytest.raises(TrialRecordError, match="epoch_id must be a non-empty string"):
        _record(epoch_id=bad)


# -- The provenance triple -----------------------------------------------------


EVALUATOR_HASH = "27f6343f980c4c0ab821d9c72d211d0eb76b0853825cefd80476a05e43cab27e"
SNAPSHOT_HASH = "16a0eeb0791b6c92451fd284dd9f599e0a7dbe7f6ebea6e2d2d06c7f74aec112"
COST_MODEL_HASH = "7ceff1a68ddd995b2e87790bad3d75edd4bd42da19cf19039af8888851a7f520"


def test_the_triple_is_carried_in_the_hexdigests_own_spelling() -> None:
    # The three columns hold the sha256 hexdigests their owning features
    # computed — feature 70's evaluator, §4.2's snapshot, feature 60's
    # cost model — and this layer holds each to being that digest, in its
    # canonical lowercase spelling, coin and canonicalise none of it.
    record = _record(
        evaluator_hash=EVALUATOR_HASH,
        snapshot_hash=SNAPSHOT_HASH,
        cost_model_hash=COST_MODEL_HASH,
    )
    assert record.evaluator_hash == EVALUATOR_HASH
    assert record.snapshot_hash == SNAPSHOT_HASH
    assert record.cost_model_hash == COST_MODEL_HASH


def test_uppercase_hex_is_folded_to_the_digests_own_case() -> None:
    # A hash pasted from a report or a log line is commonly uppercase and
    # means the same value; the record carries the one spelling the
    # CHAR(64) columns hold, the same fold the evaluator and snapshot
    # members give the sibling columns this row joins against.
    record = _record(evaluator_hash=EVALUATOR_HASH.upper())
    assert record.evaluator_hash == EVALUATOR_HASH


def test_none_is_the_pre_stamp_reads_spelling_for_the_triple() -> None:
    # The record is also the read, and a row written before the triple
    # landed — on a table the legacy upgrade brought forward — honestly
    # names no provenance.  ``None`` is that statement for all three
    # terms; it is refused at the write seams, never here.
    record = _record()
    assert record.evaluator_hash is None
    assert record.snapshot_hash is None
    assert record.cost_model_hash is None


@pytest.mark.parametrize(
    "bad",
    [
        "27f6343f980c4c0ab821d9c72d211d0eb76b0853825cefd80476a05e43cab27",  # 63
        "27f6343f980c4c0ab821d9c72d211d0eb76b0853825cefd80476a05e43cab27ef",  # 65
        "sha256:27f6343f980c4c0ab821d9c72d211d0eb76b0853825cefd80476a05e43cab27e",
        "z7f6343f980c4c0ab821d9c72d211d0eb76b0853825cefd80476a05e43cab27e",
        "   ",
        7,
        1.5,
        True,
        [],
        object(),
    ],
)
def test_a_term_that_is_not_64_hex_characters_is_refused(bad: object) -> None:
    # Short, long, prefixed, non-hex, blank and non-string all name no
    # evaluator, snapshot or cost model this system recorded.  The read
    # revalidates through this same check, which is how a hand-edited row
    # whose provenance wandered into a value that names nothing is
    # refused rather than served.
    with pytest.raises(TrialRecordError, match="evaluator_hash"):
        _record(evaluator_hash=bad)


def test_an_image_reference_is_refused_on_its_own_ground() -> None:
    # The prefixed spelling is the one refusal with its own message: a
    # sha256:<hex> digest is an *image reference*, and a row stamped with
    # one would name no evaluator this system recorded while looking
    # exactly like a row that does.
    with pytest.raises(TrialRecordError, match="image reference"):
        _record(snapshot_hash=f"sha256:{EVALUATOR_HASH}")
