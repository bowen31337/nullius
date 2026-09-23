"""Feature 288: a backfilled world persisted with its originating campaign.

app_spec.xml, "Regime Coverage Strata", feature 288: *System persists a
backfilled world with its originating campaign reference, so backfill
never masquerades as fresh history.*  The feature's whole sentence is a
negative — *never masquerades* — so the tests below are written as the
two halves of that claim: a backfilled world **is** recorded with the
campaign it came from, and a world that cannot say where it came from is
**refused** rather than seated.

The suite is deliberately split the way the module is:

* :func:`split_world_id` is the pure half — feature 287 spelled the world
  id ``<campaign_id>@<epoch_id>`` so that the provenance *is* the
  identity, and this function is the one place the member reads those two
  halves back out.  Its tests pin the spelling (including the parts it
  must **not** normalise: the separator is never folded away and a half is
  never re-spelled) and pin each way a world can fail to state an origin.
* :class:`~regime.origins.WorldBackfill` is the act — the store that
  records one world's origin in this member's own table.  Its tests pin
  the seat, the idempotence (a re-run of a backfill is the ordinary case
  and must not move the vintage), the read path's validation, and the
  question the feature turns on: *was this world written by a backfill?*

Two tests are worth calling out because they are the *feature* rather than
its mechanics.  :func:`test_backfill_and_fresh_history_are_distinguishable`
is §C7's coverage number staying honest: a synthetic world and a world the
system really ran must not answer the same way to the store's one
question.  And
:func:`test_a_world_that_cannot_name_its_tree_is_never_seated` is the
masquerade refused at the door — the world is not written, so nothing
downstream can count it.

A few tests pin the *naming*, which is load-bearing rather than cosmetic:
feature 287's implementation lands in this same member as
``regime.backfill`` / ``BackfilledWorld`` / ``BackfillCoverageError``, and
this feature's store would sit one character away from all three if it were
called ``backfilled`` / ``BackfilledWorlds``.  A wrong import of a
near-miss name succeeds and means something else, so the module is
``regime.origins`` and the store is ``WorldBackfill`` — see
:func:`test_the_store_is_not_named_a_character_from_its_siblings`.

The stand-ins follow the shape the census suite established: a carrier is
duck-typed (`__slots__`, no imports from another member), because no
member imports another and the composed loader serves a *second* class
object of the same shape — an ``isinstance`` gate would refuse the very
world the composition seam hands out.
"""

from __future__ import annotations

import sqlite3
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest
from regime import (
    BACKFILLED_WORLD_TABLE,
    CAMPAIGN_ID_COLUMN,
    EPOCH_ID_COLUMN,
    NO_ORIGIN_CODE,
    RECORDED_AT_COLUMN,
    WORLD_ID_COLUMN,
    WORLD_ID_SEPARATOR,
    BackfilledWorldRecord,
    BackfillProvenance,
    BackfillProvenanceError,
    CoverageError,
    RegimeCoverage,
    WorldBackfill,
    record_backfilled_world,
    split_world_id,
)

#: A campaign id of the shape feature 232 mints — a UUID, which is why the
#: separator feature 287 chose can be split on naively: no campaign id
#: contains one.  Spelled as data rather than generated, so a failure reads
#: as the same two values every run.
CAMPAIGN = "3f1c0b2e-4a5d-4e6f-8a9b-0c1d2e3f4a5b"

#: An epoch id of the shape the sequestered-epoch ledger keys on — text, and
#: deliberately *not* a UUID, because this store takes the epoch half as
#: given and must not assume a spelling for it.
EPOCH = "2021-05-covid-rebound"


class _BackfilledWorld:
    """Feature 287's ``BackfilledWorld``, as this suite stands in for it.

    ``world_id`` and ``regime_rows``, exactly the two fields feature 287's
    spec states — and nothing else, which is what makes it a real test of
    the duck-typed seam: the store must read an origin out of the id alone,
    because the id is all there is.  ``__slots__`` because the composed
    loader's second-class-object problem is a *shape* problem and slots make
    the shape the whole object.
    """

    __slots__ = ("regime_rows", "world_id")

    def __init__(self, world_id: str, regime_rows: tuple = ()) -> None:
        self.world_id = world_id
        self.regime_rows = regime_rows


class _StatedOrigin:
    """A carrier that *volunteers* a campaign or an epoch beside its id.

    Not feature 287's shape, and deliberately so: this stand-in exists to
    pin what happens when a carrier states an origin the id disagrees with.
    The store must refuse rather than pick a half to believe — a world
    stating two origins has none a reader could rely on.
    """

    __slots__ = ("campaign_id", "epoch_id", "world_id")

    def __init__(
        self,
        world_id: str,
        campaign_id: str | None = None,
        epoch_id: str | None = None,
    ) -> None:
        self.world_id = world_id
        self.campaign_id = campaign_id
        self.epoch_id = epoch_id


def _world_id(campaign: str = CAMPAIGN, epoch: str = EPOCH) -> str:
    """The identity feature 287 spells — one place, so the spelling is data."""
    return f"{campaign}{WORLD_ID_SEPARATOR}{epoch}"


@pytest.fixture
def worlds(database_url: str) -> WorldBackfill:
    """The store, pointed at this test's own fresh database.

    No migration has run and none is needed: the store creates its table
    idempotently on first use, the contract every member store in this
    workspace takes toward a table it alone writes.  See
    :func:`test_the_first_record_is_what_creates_the_table` for the
    assertion that this is what actually happens.
    """
    return WorldBackfill(database_url)


# -- The spelling: reading an origin out of a world id ------------------------


def test_a_world_id_carries_its_campaign_and_its_epoch():
    """Feature 287's ``<campaign_id>@<epoch_id>``, read back out.

    The load-bearing half of *the provenance is the identity*: the two
    halves a reader resolves — the campaign the tree belongs to, the epoch
    it was replayed against — come out of the one string, so a store of
    origins has no second value to be handed and cannot be told two stories.
    """
    provenance = split_world_id(_world_id())

    assert provenance.campaign_id == CAMPAIGN
    assert provenance.epoch_id == EPOCH
    assert (provenance.originating_campaign, provenance.epoch_id) == (
        provenance.campaign_id,
        provenance.epoch_id,
    )


def test_the_origin_is_derived_from_the_id_and_never_a_second_field():
    """One fact, one spelling: the provenance is a *view* of the identity.

    Asserted structurally rather than by reading the implementation:
    :class:`BackfillProvenance` is what the split *returns*, so a store that
    took a separate ``campaign_id`` argument would be accepting a second
    opinion about a fact its own key already carries — the ambiguity this
    feature exists to remove rather than relocate.
    """
    assert tuple(BackfillProvenance.__dataclass_fields__) == (
        "campaign_id",
        "epoch_id",
    )
    provenance = split_world_id(_world_id())
    assert provenance.row() == {
        CAMPAIGN_ID_COLUMN: CAMPAIGN,
        EPOCH_ID_COLUMN: EPOCH,
    }


def test_the_row_is_a_fresh_mapping_every_call():
    """``row()`` renders a new dict, the discipline every record here keeps.

    A cached mapping handed to two callers is one caller's edit away from
    being the other's record; feature 287's own spec asks for *a fresh
    mapping* and this is the same law one module over.
    """
    provenance = split_world_id(_world_id())

    first, second = provenance.row(), provenance.row()
    assert first == second and first is not second
    first["mutated"] = True
    assert "mutated" not in provenance.row()


def test_the_separator_is_split_on_its_first_occurrence():
    """Everything after the first ``@`` is the epoch, taken as given.

    Campaign ids are UUIDs and contain no ``@``; epoch ids are text and this
    store has no business re-spelling them.  So an epoch that happens to
    contain the separator survives intact — a split on the *last* one, or a
    naive ``split`` demanding exactly two parts, would silently truncate an
    identity the sequestered-epoch ledger minted.
    """
    provenance = split_world_id(f"{CAMPAIGN}@a@b")

    assert provenance.campaign_id == CAMPAIGN
    assert provenance.epoch_id == "a@b"


def test_the_halves_are_stripped_but_never_re_spelled():
    """Whitespace around a half is noise; the half itself is not touched.

    The separator is the member's own and is never normalised away, and a
    half is not case-folded — a caller that wrote two spellings of one
    campaign reconciles them in the campaign table that mints them, not
    here, where a "helpful" rewrite would silently rename the provenance a
    world id carries.
    """
    provenance = split_world_id(f"  {CAMPAIGN}  @\t{EPOCH}\n")

    assert provenance.campaign_id == CAMPAIGN
    assert provenance.epoch_id == EPOCH

    mixed = split_world_id("Camp-1@EPOCH-9")
    assert mixed.campaign_id == "Camp-1"
    assert mixed.epoch_id == "EPOCH-9"


@pytest.mark.parametrize(
    "world_id",
    [
        pytest.param(f"{CAMPAIGN}{WORLD_ID_SEPARATOR}", id="blank-epoch"),
        pytest.param(f"{WORLD_ID_SEPARATOR}{EPOCH}", id="blank-campaign"),
        pytest.param(WORLD_ID_SEPARATOR, id="separator-only"),
        pytest.param("   @   ", id="whitespace-halves"),
    ],
)
def test_a_half_that_states_nothing_is_refused(world_id: str):
    """An empty half names no campaign (or no epoch) a reader could resolve.

    One code for all of them — ``no_origin`` — because the repair is the
    same in every case: re-derive the world from the tree and the epoch it
    was really synthesized from.
    """
    with pytest.raises(BackfillProvenanceError) as caught:
        split_world_id(world_id)

    assert str(caught.value).startswith(NO_ORIGIN_CODE)


def test_a_world_id_with_no_separator_states_no_originating_campaign():
    """The feature's own sentence, refused.

    A world named without a campaign is a synthetic world that could be
    counted as fresh history — which is precisely the masquerade feature
    288 exists to refuse, and the refusal must say so rather than seating a
    row with an empty column.
    """
    with pytest.raises(BackfillProvenanceError) as caught:
        split_world_id("a-world-with-no-origin")

    message = str(caught.value)
    assert message.startswith(NO_ORIGIN_CODE)
    assert "a-world-with-no-origin" in message
    assert "feature 288" in message


@pytest.mark.parametrize("not_text", [None, 17, 3.5, b"bytes", ["a@b"]])
def test_a_world_id_that_is_not_text_is_refused(not_text):
    """An id is text — the pool's key is a string, in every table that holds it."""
    with pytest.raises(BackfillProvenanceError) as caught:
        split_world_id(not_text)

    assert str(caught.value).startswith(NO_ORIGIN_CODE)


# -- The record: the value the table holds ------------------------------------


def test_the_provenance_refuses_a_blank_half_built_directly():
    """Validated in ``__post_init__``, not only at the split.

    ``dataclasses.replace`` and unpickling both rebuild an instance past a
    factory's nose — the argument the sibling records state for their own
    fields — so the check has to live on the value itself.  This is what
    makes a cell built from a stored row as trustworthy as one built from a
    freshly split id.
    """
    with pytest.raises(BackfillProvenanceError):
        BackfillProvenance(campaign_id="  ", epoch_id=EPOCH)
    with pytest.raises(BackfillProvenanceError):
        BackfillProvenance(campaign_id=CAMPAIGN, epoch_id="")


def test_a_backfilled_world_record_is_frozen():
    """A caller cannot re-type the pool's provenance in memory.

    The row is what the dreaming loop and the coverage endpoint read; a
    record that could be edited after the fact would let a caller change
    what a synthetic world claims to be without touching the row anyone
    else sees.
    """
    record = BackfilledWorldRecord(
        world_id=_world_id(),
        campaign_id=CAMPAIGN,
        epoch_id=EPOCH,
        recorded_at="2026-01-01 00:00:00",
    )

    with pytest.raises(FrozenInstanceError):
        record.campaign_id = "someone-else"  # type: ignore[misc]


def test_a_record_whose_halves_contradict_its_id_is_refused():
    """The read path's check, and it is sharper than a type test.

    SQLite's columns are dynamically typed, so a raw ``INSERT`` from another
    tool can land a ``campaign_id`` disagreeing with the ``world_id`` beside
    it.  A record that carried both without comparing them would hand a
    caller exactly the ambiguous provenance this feature refuses — so the
    value re-derives the origin from the id and refuses the disagreement.
    """
    with pytest.raises(BackfillProvenanceError) as caught:
        BackfilledWorldRecord(
            world_id=_world_id(),
            campaign_id="a-different-campaign",
            epoch_id=EPOCH,
            recorded_at="2026-01-01 00:00:00",
        )

    message = str(caught.value)
    assert message.startswith(NO_ORIGIN_CODE)
    assert "a-different-campaign" in message

    with pytest.raises(BackfillProvenanceError):
        BackfilledWorldRecord(
            world_id=_world_id(),
            campaign_id=CAMPAIGN,
            epoch_id="a-different-epoch",
            recorded_at="2026-01-01 00:00:00",
        )


def test_a_record_without_a_vintage_is_refused():
    """``recorded_at`` is ``NOT NULL``; a row without one reports nothing.

    A recorded origin with no instant is not evidence of when the pool grew,
    so a row missing its vintage is a row this store cannot report — the
    third face of the ``no_origin`` refusal.
    """
    with pytest.raises(BackfillProvenanceError) as caught:
        BackfilledWorldRecord(
            world_id=_world_id(),
            campaign_id=CAMPAIGN,
            epoch_id=EPOCH,
            recorded_at=None,
        )

    assert str(caught.value).startswith(NO_ORIGIN_CODE)


def test_the_record_renders_the_tables_own_column_names():
    """The row is the record: one spelling, keyed the way the table is.

    A rendered mapping that invented its own names would be a second
    vocabulary for one fact, and the drift would only show up in whatever
    read the mapping and the row side by side.
    """
    record = BackfilledWorldRecord(
        world_id=_world_id(),
        campaign_id=CAMPAIGN,
        epoch_id=EPOCH,
        recorded_at="2026-01-01 00:00:00",
    )

    assert record.row() == {
        WORLD_ID_COLUMN: _world_id(),
        CAMPAIGN_ID_COLUMN: CAMPAIGN,
        EPOCH_ID_COLUMN: EPOCH,
        RECORDED_AT_COLUMN: "2026-01-01 00:00:00",
    }
    assert record.provenance == BackfillProvenance(CAMPAIGN, EPOCH)
    assert record.originating_campaign == CAMPAIGN


# -- The act: recording a backfilled world ------------------------------------


def test_the_first_record_is_what_creates_the_table(worlds, database_url):
    """No migration runs, and none is needed — the store creates its table.

    The stance every member store here takes toward a table it alone writes
    (feature 254's ``replay_latency_metrics``, feature 188's
    ``bootstrap_world``): a fresh database, one the coverage ledger already
    lives in, and one a migration built all take the same write path.

    Pinned by *inspecting the file* rather than by trusting the store: the
    database did not exist before the call, and the table is in it after.
    """
    path = Path(database_url.removeprefix("sqlite:///"))
    assert not path.exists()

    record = worlds.record(_BackfilledWorld(_world_id()))

    assert path.exists()
    with sqlite3.connect(path) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
    assert BACKFILLED_WORLD_TABLE in tables
    assert record.world_id == _world_id()


def test_the_recorded_origin_is_what_the_store_reads_back(worlds):
    """The row is the record — never a value assembled from the argument.

    The answer is read out of the table inside the same transaction as the
    write, so a caller holding a record knows what the *pool* holds rather
    than what it hoped to write.
    """
    record = worlds.record(_BackfilledWorld(_world_id()))

    assert isinstance(record, BackfilledWorldRecord)
    assert record.campaign_id == CAMPAIGN
    assert record.epoch_id == EPOCH
    assert record.recorded_at is not None
    assert worlds.get(_world_id()) == record


def test_a_bare_world_id_is_a_carrier(worlds):
    """A world id *is* the whole of what is persisted.

    The one attribute the act needs is ``world_id``; a caller that holds
    only the name is not made to invent a wrapper around it.  The seat is
    keyed by the name a ``replay_score`` row attributes a score to, and that
    name is the entire input.
    """
    record = worlds.record(_world_id())

    assert record.world_id == _world_id()
    assert worlds.is_backfilled(_world_id())


def test_a_world_without_an_id_is_refused_by_name(worlds):
    """A carrier that cannot name itself cannot have an origin recorded."""
    with pytest.raises(BackfillProvenanceError) as caught:
        worlds.record(object())

    assert str(caught.value).startswith(NO_ORIGIN_CODE)


def test_a_world_that_cannot_name_its_tree_is_never_seated(worlds, database_url):
    """The masquerade refused at the door — nothing is written, nothing opened.

    This is feature 288's whole sentence tested as a negative, and the
    assertion is the *strong* one: validation is total before the first
    write, so the refusal happens before the store ever reaches the disk —
    the database file does not exist afterwards.  A store that wrote first
    and validated later would leave a row nothing could tell from a
    legitimate one: the synthetic world counted as fresh history, discovered
    at the promotion gate that reads §C7's number.
    """
    with pytest.raises(BackfillProvenanceError):
        worlds.record(_BackfilledWorld("a-world-with-no-origin"))

    path = Path(database_url.removeprefix("sqlite:///"))
    assert not path.exists()

    # And a *seated* world is unaffected by a later refusal — the check is on
    # the ask, never a truncation of what the store already holds.
    worlds.record(_world_id())
    with pytest.raises(BackfillProvenanceError):
        worlds.record("another-world-with-no-origin")
    assert [record.world_id for record in worlds.worlds()] == [_world_id()]


def test_a_carrier_stating_an_origin_that_contradicts_its_id_is_refused(worlds):
    """A world stating two origins has none a reader could rely on.

    The store derives the origin from the identity and *checks* a volunteered
    one rather than believing it, so there is nothing to choose between and
    no way to seat a world whose id and whose fields disagree.  The refusal
    names both spellings, because the operator has to reconcile them in
    whatever configuration assembled the world.
    """
    with pytest.raises(BackfillProvenanceError) as caught:
        worlds.record(
            _StatedOrigin(_world_id(), campaign_id="some-other-campaign")
        )

    message = str(caught.value)
    assert message.startswith(NO_ORIGIN_CODE)
    assert "some-other-campaign" in message
    assert CAMPAIGN in message

    with pytest.raises(BackfillProvenanceError):
        worlds.record(_StatedOrigin(_world_id(), epoch_id="1867-somewhere-else"))


def test_a_carrier_stating_an_origin_that_agrees_with_its_id_is_seated(worlds):
    """A volunteered origin that *matches* is not an error — it is redundant.

    The check refuses disagreement, not the stating.  A carrier that repeats
    what its id already spells is seated exactly as a bare one is, so the
    seam stays open to a future world that carries its halves explicitly.
    """
    record = worlds.record(_StatedOrigin(_world_id(), CAMPAIGN, EPOCH))

    assert record.campaign_id == CAMPAIGN
    assert record.epoch_id == EPOCH


# -- Idempotence: a re-run of the backfill ------------------------------------


def test_a_re_issued_record_returns_the_standing_row_byte_for_byte(worlds):
    """A backfill is a batch job; re-running it is the ordinary case.

    The instant recorded is *when this world first entered the pool as a
    backfill*, and a retry did not move it — so the second call returns the
    first call's row, vintage included, rather than re-stamping it.  A
    re-stamped vintage would say the pool grew again when it did not.
    """
    first = worlds.record(_BackfilledWorld(_world_id()))
    second = worlds.record(_BackfilledWorld(_world_id()))
    third = worlds.record(_world_id())

    assert first == second == third
    assert first.recorded_at == second.recorded_at == third.recorded_at
    assert len(worlds.worlds()) == 1


def test_the_vintage_comes_from_the_database_and_not_from_python(worlds, database_url):
    """One clock, and it is the database's.

    Nothing in this module computes a timestamp: the column carries the
    table's own ``DEFAULT (datetime('now'))``, so a writer-minted instant can
    never disagree with a default-minted one about which world was seated
    first.  Pinned by comparing the stored value to what SQLite itself
    answers — a Python ``datetime.now()`` would not match to the second.
    """
    record = worlds.record(_world_id())

    with sqlite3.connect(Path(database_url.removeprefix("sqlite:///"))) as connection:
        (engine_says,) = connection.execute(
            "SELECT datetime('now')"
        ).fetchone()
    assert record.recorded_at == engine_says


def test_the_ddl_default_keeps_its_outer_parentheses():
    """The trap SQLite's ``DEFAULT`` grammar sets, pinned as text.

    A ``DEFAULT`` holding a bare function call is a syntax error that takes
    the whole ``CREATE TABLE`` down — and it would only ever be discovered
    by a deployment whose store created the table first.  Cheaper to read
    the DDL: the expression is parenthesised.
    """
    from regime.origins import _SCHEMA

    assert "DEFAULT (datetime('now'))" in _SCHEMA
    assert "IF NOT EXISTS" in _SCHEMA
    assert "PRIMARY KEY" in _SCHEMA
    assert RECORDED_AT_COLUMN in _SCHEMA


def test_a_seat_raced_by_two_workers_leaves_one_row_and_no_dbapi_error(
    database_url,
):
    """The seating is idempotent *in the engine*, not by a read-then-write.

    Feature 287's backfill is a batch job over stored trees crossed with
    historical epochs, so a re-run against a partially-seated pool is the
    ordinary case — and two workers can reach the same world id at once.  A
    plain ``INSERT`` behind a prior read would let the loser of that race
    raise a raw ``sqlite3.IntegrityError`` out of a member act, which is a
    DBAPI exception where this member's ``no_origin`` vocabulary belongs.

    Simulated without threads by seating *past* the read: the world is
    written by a raw connection first, so the store's insert genuinely
    conflicts rather than merely finding a row a moment earlier.  The clause
    is what turns that conflict into a no-op — asserted directly, because a
    test that only ever took the "already there" path would pass just as
    happily against a plain ``INSERT``.
    """
    path = Path(database_url.removeprefix("sqlite:///"))
    first = WorldBackfill(database_url)
    seated = first.record(_world_id())

    # A second store, opened against the same database, re-issues the record.
    second = WorldBackfill(database_url)
    raced = second.record(_world_id())

    assert raced == seated
    assert raced.recorded_at == seated.recorded_at
    assert len(second.worlds()) == 1

    # The collision is real, not incidental: the same statement without its
    # ON CONFLICT arm raises.  Read straight off the module's own SQL so the
    # two statements cannot drift apart.
    from regime.origins import _INSERT_ROW_SQL

    with sqlite3.connect(path) as connection, pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            _INSERT_ROW_SQL.split("ON CONFLICT")[0].strip(),
            (_world_id(), CAMPAIGN, EPOCH),
        )


def test_two_worlds_from_one_campaign_are_two_rows(worlds):
    """The epoch is the other half of the identity, not a detail of it.

    One tree replayed against two historical epochs is *two* synthetic
    worlds — the campaign reference is the same and the world ids differ —
    and a store keyed on the campaign would collapse them into one row and
    lose a world from the count §C7 reports.
    """
    first = worlds.record(_world_id(epoch="2021-05-covid-rebound"))
    second = worlds.record(_world_id(epoch="2022-10-rates-shock"))

    assert first.campaign_id == second.campaign_id == CAMPAIGN
    assert first.world_id != second.world_id
    assert len(worlds.worlds()) == 2


# -- The question the feature turns on ----------------------------------------


def test_backfill_and_fresh_history_are_distinguishable(worlds):
    """§C7's coverage number staying honest — the feature, end to end.

    A world the backfill synthesized and a world the system really traded
    must not answer the same way to the store's one question.  Both ids are
    well-formed and both would be counted by §C7's ledger; only the
    synthetic one is recorded here, and that recorded fact is what lets a
    reader tell them apart instead of counting the backfill as history.
    """
    synthetic = _world_id()
    fresh = "replay-of-a-real-run"

    worlds.record(_BackfilledWorld(synthetic))

    assert worlds.is_backfilled(synthetic) is True
    assert worlds.is_backfilled(fresh) is False
    assert worlds.get(fresh) is None


def test_the_backfilled_worlds_are_listed_in_the_keys_order(worlds):
    """The pool's backfilled half, enumerated and comparable.

    Ordered by the table's key so two reads of one store agree — the law
    every listing in this workspace keeps — and a tuple rather than a live
    cursor, because the answer is a value the caller keeps rather than a
    view that changes under it.
    """
    ids = [_world_id(epoch=epoch) for epoch in ("c-epoch", "a-epoch", "b-epoch")]
    for world_id in ids:
        worlds.record(world_id)

    listed = [record.world_id for record in worlds.worlds()]
    assert listed == sorted(ids)
    assert all(record.campaign_id == CAMPAIGN for record in worlds.worlds())


def test_an_empty_store_answers_none_and_false_rather_than_raising(worlds):
    """Absent is an answer, not a failure — and not a broken store.

    ``None`` from :meth:`~regime.origins.WorldBackfill.get` means *this
    world was not recorded by a backfill*, which is the honest fact that
    keeps a fresh world distinguishable from a synthetic one.  An unreachable
    database *raises*, so a caller can never mistake a broken store for a
    fresh world.
    """
    assert worlds.get(_world_id()) is None
    assert worlds.is_backfilled(_world_id()) is False
    assert worlds.worlds() == ()


def test_a_blank_world_id_is_refused_rather_than_answered_false(worlds):
    """A malformed ask is not a fresh world — the two must not collapse.

    ``False`` means *nothing recorded this name as backfilled*; a name that
    states nothing is a caller error, and answering ``False`` would let a
    mis-built id pass as a legitimate fresh one.
    """
    for blank in ("", "   ", None, 17):
        with pytest.raises(BackfillProvenanceError):
            worlds.is_backfilled(blank)
        with pytest.raises(BackfillProvenanceError):
            worlds.get(blank)


# -- The read path validates what it reads ------------------------------------


def test_a_row_written_by_another_tool_is_validated_on_read(worlds, database_url):
    """SQLite's columns are dynamically typed, so the read path checks too.

    A raw ``INSERT`` that lands a ``campaign_id`` disagreeing with the
    ``world_id`` beside it is exactly the ambiguous provenance this feature
    refuses — and it must be refused on the way *out* as well, or the
    masquerade arrives through the read path instead of the write path.  The
    refusal names the world it came off, so the operator learns which row to
    look at.
    """
    worlds.record(_world_id())
    path = Path(database_url.removeprefix("sqlite:///"))
    with sqlite3.connect(path) as connection:
        connection.execute(
            f"UPDATE {BACKFILLED_WORLD_TABLE} SET {CAMPAIGN_ID_COLUMN} = ? "
            f"WHERE {WORLD_ID_COLUMN} = ?",
            ("an-outside-tool-wrote-this", _world_id()),
        )

    with pytest.raises(BackfillProvenanceError) as caught:
        worlds.get(_world_id())

    message = str(caught.value)
    assert _world_id() in message
    assert "an-outside-tool-wrote-this" in message

    with pytest.raises(BackfillProvenanceError):
        worlds.worlds()


def test_the_table_itself_refuses_a_row_with_no_vintage(worlds, database_url):
    """The vintage face, pinned where it actually bites: the constraint.

    ``NOT NULL`` is the first line of defence — another tool cannot land a
    row without a vintage at all, because the insert refuses.  That is why
    the record's own check is written for the value built *directly* (see
    :func:`test_a_record_without_a_vintage_is_refused`) rather than for a
    row, and pinning the constraint here is what keeps the two claims from
    being confused for one another: the column is the guarantee, the value's
    check is the belt to its braces.
    """
    worlds.record(_world_id())
    path = Path(database_url.removeprefix("sqlite:///"))
    with sqlite3.connect(path) as connection, pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            f"UPDATE {BACKFILLED_WORLD_TABLE} SET {RECORDED_AT_COLUMN} = NULL "
            f"WHERE {WORLD_ID_COLUMN} = ?",
            (_world_id(),),
        )

    # Nothing was corrupted by the attempted write.
    assert worlds.get(_world_id()).recorded_at is not None


# -- The address ---------------------------------------------------------------


def test_a_non_sqlite_url_is_refused_in_the_members_address_vocabulary():
    """An address fault is not a provenance fault, and the repair differs.

    Pointing the deployment at a database this member cannot speak has
    nothing to do with a world's origin, so it raises
    :class:`~regime.errors.CoverageError` — the class that already carries the
    address face for the same variable — rather than the ``no_origin`` class.
    A caller catching them together would read *the world's origin was
    ambiguous* where the truth is *the deployment is wired wrong*.
    """
    store = WorldBackfill("postgresql://localhost/regime")

    with pytest.raises(CoverageError) as caught:
        store.record(_world_id())
    assert not isinstance(caught.value, BackfillProvenanceError)


def test_an_in_memory_url_is_refused():
    """A record must outlive the call that wrote it.

    The dreaming loop and the coverage endpoint read the pool's worlds from
    another process, between this process's calls — so an in-memory database
    would take the pool's provenance with it when the connection closed.
    """
    store = WorldBackfill("sqlite:///:memory:")

    with pytest.raises(CoverageError):
        store.record(_world_id())


def test_a_store_without_a_url_is_refused():
    """A store pointed at nothing has nowhere to record an origin."""
    for blank in ("", "   ", None, 17):
        with pytest.raises(CoverageError):
            WorldBackfill(blank)


def test_construction_opens_no_database(database_url):
    """Composition-time work must not touch the disk.

    The factory builds every registered component on every ``create_app()``
    call, so the store resolves its path on first use and opens nothing
    until an operation needs it — the promise the member's own builder
    makes, restated for the store this feature adds.
    """
    path = Path(database_url.removeprefix("sqlite:///"))
    store = WorldBackfill(database_url)

    assert not path.exists()
    assert store.path == path  # resolving is not opening


# -- The module-level spelling -------------------------------------------------


def test_record_backfilled_world_records_through_a_named_url(database_url):
    """The feature's sentence as one call, for a caller holding no store."""
    record = record_backfilled_world(_BackfilledWorld(_world_id()), database_url=database_url)

    assert record.campaign_id == CAMPAIGN
    assert WorldBackfill(database_url).is_backfilled(_world_id())


def test_record_backfilled_world_resolves_the_environment(database_url):
    """The same variable the coverage ledger resolves — one deployment, one URL.

    A census script and a composed application must reach the same database;
    the store this feature adds lives in it.
    """
    record = record_backfilled_world(
        _world_id(), env={"DATABASE_URL": database_url}
    )

    assert record.world_id == _world_id()
    assert WorldBackfill(database_url).is_backfilled(_world_id())


def test_record_backfilled_world_refuses_when_nothing_names_a_store():
    """A record that quietly skipped its write is the masquerade.

    Refused *by name* rather than silently doing nothing: a deployment that
    named no store would otherwise leave the pool holding synthetic worlds
    indistinguishable from fresh history, and §C7's number would be inflated
    by worlds the system never ran — discovered at the promotion gate that
    reads it.
    """
    with pytest.raises(CoverageError) as caught:
        record_backfilled_world(_world_id(), env={})

    assert "DATABASE_URL" in str(caught.value)


def test_the_store_resolves_the_environment_and_names_its_absence():
    """:meth:`WorldBackfill.resolve` — a discoverable state, not an exception."""
    assert WorldBackfill.resolve({}) is None
    assert WorldBackfill.resolve({"DATABASE_URL": "  "}) is None

    resolved = WorldBackfill.resolve({"DATABASE_URL": "sqlite:///somewhere.db"})
    assert isinstance(resolved, WorldBackfill)
    assert resolved.database_url == "sqlite:///somewhere.db"


# -- The member's shape --------------------------------------------------------


def test_the_feature_registers_no_component():
    """A store addressed by ``DATABASE_URL`` is never composed.

    The registered surface stays feature 283's single ledger — the law the
    member's own docstring argues — so this feature adds no builder, and
    ``app.order`` and every name-sorted adjacency assertion in the workspace
    are untouched.  (The member suite's ``test_component`` asserts the
    builder list independently; this is the same fact stated where the
    feature that could have broken it lives.)
    """
    import regime

    assert [
        name for name in dir(regime) if name.startswith("build_")
    ] == ["build_regime_coverage"]


def test_every_refusal_opens_with_the_greppable_code(worlds, database_url):
    """``no_origin`` is greppable, so *every* message has to carry it once.

    The error class's docstring promises this and it is the whole reason the
    code exists: an operator greps one word to find every refusal of this
    fact in a log.  A promise about *all* messages is exactly the kind that
    rots the moment someone adds a raise, so it is walked here rather than
    left to inspection — every path below reaches a different ``raise``.
    """
    path = Path(database_url.removeprefix("sqlite:///"))
    prefix = f"{NO_ORIGIN_CODE}: "

    def _refusals():
        # the split: no separator, a blank half, non-text
        for bad_id in ("no-origin", f"{CAMPAIGN}{WORLD_ID_SEPARATOR}", None):
            yield lambda bad_id=bad_id: split_world_id(bad_id)
        # the carrier: no id at all
        yield lambda: worlds.record(object())
        # the disagreement: a stated half contradicting the id
        yield lambda: worlds.record(_StatedOrigin(_world_id(), campaign_id="other"))
        # the record, built directly: a contradicting half, then no vintage
        yield lambda: BackfilledWorldRecord(
            world_id=_world_id(), campaign_id="other", epoch_id=EPOCH, recorded_at="t"
        )
        yield lambda: BackfilledWorldRecord(
            world_id=_world_id(), campaign_id=CAMPAIGN, epoch_id=EPOCH, recorded_at=None
        )

    for refusal in _refusals():
        with pytest.raises(BackfillProvenanceError) as caught:
            refusal()
        message = str(caught.value)
        assert message.startswith(prefix), message
        assert message.count(NO_ORIGIN_CODE) == 1, f"doubled code: {message}"

    # And the read path, whose re-raise re-frames an inner message that
    # already carries the code — the one place a doubled prefix could creep in.
    worlds.record(_world_id())
    with sqlite3.connect(path) as connection:
        connection.execute(
            f"UPDATE {BACKFILLED_WORLD_TABLE} SET {CAMPAIGN_ID_COLUMN} = ?",
            ("an-outside-tool-wrote-this",),
        )
    with pytest.raises(BackfillProvenanceError) as caught:
        worlds.worlds()
    message = str(caught.value)
    assert message.startswith(prefix), message
    assert message.count(NO_ORIGIN_CODE) == 1, f"doubled code: {message}"
    assert _world_id() in message


def test_the_world_id_column_is_text_and_not_a_uuid(worlds, database_url):
    """A backfilled world's id is not a UUID, and the type says so.

    The spec declares ``replay_score.world_id`` as ``UUID``; feature 287's
    backfilled spelling is ``<campaign_id>@<epoch_id>``, which is not one.
    The two tables still join on the same *name*, and that is fine — SQLite
    stores what it is given — but declaring this column ``TEXT`` is this
    table's statement about what the value *is*.  A later reader that
    "corrected" it to match ``replay_score`` would be declaring a synthetic
    world's id a UUID, and a UUID-typed read of a backfilled world's name is
    the masquerade arriving through the type.

    Pinned against the workspace's own convention too: both the dreaming
    member's score table and the bootstrap pool declare ``world_id TEXT``.
    """
    from regime.origins import _SCHEMA

    # The *column declarations*, not the whole text: the DDL's prose explains
    # the UUID contrast, so a blanket substring check would forbid the very
    # comment that records the decision.
    declarations = [
        line.strip()
        for line in _SCHEMA.splitlines()
        if line.strip().startswith(tuple(f"{c} " for c in (
            WORLD_ID_COLUMN, CAMPAIGN_ID_COLUMN, EPOCH_ID_COLUMN, RECORDED_AT_COLUMN
        )))
    ]
    assert declarations == [
        f"{WORLD_ID_COLUMN}    TEXT NOT NULL PRIMARY KEY,",
        f"{CAMPAIGN_ID_COLUMN} TEXT NOT NULL,",
        f"{EPOCH_ID_COLUMN}    TEXT NOT NULL,",
        f"{RECORDED_AT_COLUMN} TIMESTAMPTZ NOT NULL DEFAULT (datetime('now'))",
    ]
    assert not any("UUID" in line for line in declarations)

    # And the value really is un-UUID-shaped, stored and read back verbatim.
    record = worlds.record(_world_id())
    assert WORLD_ID_SEPARATOR in record.world_id
    assert record.world_id == f"{CAMPAIGN}{WORLD_ID_SEPARATOR}{EPOCH}"


def test_the_store_is_not_named_a_character_from_its_siblings():
    """The naming law, pinned — a near-miss import succeeds and means the wrong thing.

    Feature 287's implementation lands in this same member as
    ``regime.backfill`` / ``BackfilledWorld`` / ``BackfillCoverageError``:
    the verb that synthesizes worlds, and the world value itself.  This
    feature's store is the *other* act — recording where a synthesized world
    came from — so its names are deliberately a whole word away rather than
    an edit distance of one.  ``regime.backfilled`` would be a one-character
    hop from ``regime.backfill``; ``BackfilledWorlds`` is a letter away from
    ``BackfilledWorld``, *the world*.  Neither would raise: a caller would
    import something, get an object of the right rough shape, and persist or
    read the wrong thing.  Pinned as names rather than as prose because the
    names are the whole of the defence.
    """
    import regime
    from regime import origins

    assert origins.__name__ == "regime.origins"
    assert WorldBackfill.__name__ == "WorldBackfill"
    assert WorldBackfill.__module__ == "regime.origins"

    # The names 287 will own are not taken by this feature.
    for sibling_name in ("backfill_coverage", "BackfilledWorld", "BackfillCoverageError"):
        assert not hasattr(regime, sibling_name), (
            f"{sibling_name!r} belongs to feature 287, not 288 — taking the "
            "name here would make 287's landing a silent shadowing"
        )
        assert sibling_name not in regime.__all__

    # And this feature's own names are the far ones.
    assert "WorldBackfill" in regime.__all__
    assert "record_backfilled_world" in regime.__all__
    assert "split_world_id" in regime.__all__


def test_the_store_is_reachable_from_the_member_without_a_component():
    """Reached directly from the member, the way ``census_coverage`` is.

    No seat is widened and no builder returns it: the store is a value a
    caller constructs with the URL the deployment named, exactly as the
    coverage ledger is *underneath* its component.  This is what the
    spec's "no new ``@register`` component and no seat edit" buys — the
    member's ``__all__`` is the whole seam.
    """
    import regime

    assert regime.WorldBackfill is WorldBackfill
    assert regime.BackfillProvenanceError is BackfillProvenanceError
    assert regime.split_world_id is split_world_id


def test_the_new_refusal_is_a_sibling_not_a_child():
    """Error vocabulary at the seam: one repair, one ``except``.

    ``no_origin`` is not a malformed count and not a full-history fit — the
    repair is to re-derive the world, not to re-send an ask to the ledger or
    re-configure a labeler — so it sits *beside* the category's other
    refusals rather than under them, and a caller catching them together
    would read the wrong repair.
    """
    from regime import RegimeError

    assert issubclass(BackfillProvenanceError, RegimeError)
    assert not issubclass(BackfillProvenanceError, CoverageError)
    assert BackfillProvenanceError.__bases__ == (RegimeError,)


def test_the_table_is_the_members_own_and_not_the_pools_world_table():
    """Deliberately not feature 188's ``bootstrap_world``, by name.

    Seating a backfilled world in the pool's table would mean loosening
    another member's either-or ``CHECK`` — an edit to a file this member does
    not own, whose whole point is that the authored and ported halves are
    exclusive.  The alignment is *by name* instead: the same ``world_id`` a
    ``replay_score`` row joins on, in this member's own table.
    """
    assert BACKFILLED_WORLD_TABLE == "backfilled_world"
    assert BACKFILLED_WORLD_TABLE != "bootstrap_world"


def test_the_backfilled_worlds_share_a_database_with_the_coverage_ledger(
    database_url,
):
    """One deployment, one store: the ledger and the worlds live together.

    The engine creates both tables idempotently on first use, so a
    deployment that only ever ran the census gets the backfilled-world table
    the moment a backfill seats one — and neither table's creation disturbs
    the other, because they are separate statements on the same database.
    """
    ledger = RegimeCoverage(database_url)
    worlds = WorldBackfill(database_url)

    ledger.record("crash", 0)
    worlds.record(_BackfilledWorld(_world_id()))

    path = Path(database_url.removeprefix("sqlite:///"))
    with sqlite3.connect(path) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
    assert {"regime_coverage", BACKFILLED_WORLD_TABLE} <= tables
    assert ledger.get("crash").world_count == 0
    assert worlds.is_backfilled(_world_id())
