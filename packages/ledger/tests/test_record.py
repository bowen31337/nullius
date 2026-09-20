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
refusal is test_epoch.py's subject), and the value is frozen once built.
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
    # The record's column tuple is the table's declaration order, and
    # after feature 88 the epoch closes the row — the reader that unpacks
    # it cannot mistake a holdout's name for an identity, a stamp or the
    # unit.  ``None`` here is the read's spelling for a row that predates
    # the stamp; the write's required-epoch refusal is the store's and
    # the endpoint's (test_epoch.py pins both).
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
