"""Feature 191 — the ported half's persistence, and the upstream check.

app_spec.xml, "Bootstrap Worlds", feature 191: *System persists source
commit and dataset manifest hash for every ported world, which rejects a
world whose recorded values no longer match its upstream.*  The sentence
has a write half and a refusal half, and this suite holds the pool to
both:

* **"persists source commit and dataset manifest hash for every ported
  world"** — a ported world is seated by the pair of digests that pinned
  its labels, into the same ``bootstrap_world`` table the authored draw
  writes and under the ``ported`` domain §10.6's tree names fourth.  The
  row holds no seed and no draw (a ported world's identity is its
  upstream, not a draw this member made), the seating survives its own
  process, and a re-port of the *same* digests is the same world — one
  row, its first seating instant kept — which is §10.6.1's rule seen
  from the happy side: an upstream that did *not* change is not an
  updated world either.

* **"rejects a world whose recorded values no longer match its
  upstream"** — the digests the row *recorded* against the ones the
  upstream *now shows*, and the two moves a caller has: a changed
  upstream under the old world's name is refused — §10.6.1's *"an
  upstream that changes is a different world, not an updated one"*, and
  the failure table's own instruction (*"Refuse the world.  A changed
  upstream is a different world, not an updated one"*) — with the row
  left exactly as it was, never re-hashed into the pool under the name
  it no longer describes; and a changed upstream under a name of its own
  is seated as the new world it is, which is the one legal move the
  refusal leaves.

Beside the two halves of the sentence sit the store's own guards — one
pool holding both halves and counting them together, the authored reads
refusing a ported row for the plain reason they have no seed to build
from, the table's own CHECK refusing a row that is neither half, and the
legacy five-column shape feature 188 wrote, evolved with its authored
rows kept rather than stranded — each pinned by the error it raises or
the row it leaves, the discipline every store suite in this workspace
follows.
"""

from __future__ import annotations

import datetime as dt
import sqlite3
from typing import Any

import pytest
from bootstrap import (
    POOL_TABLE,
    PORTED_DOMAIN,
    BootstrapPool,
    BootstrapPoolError,
    BootstrapWorldError,
    PortedWorldRecord,
    Provenance,
    ported_world,
)

#: The digests a real port would read off its upstream — §10.6.1's
#: reference source at the commit its own paragraph pins ("not a tag,
#: not a branch"), and a manifest digest in the same vocabulary.  Opaque
#: to this member by design: the pool records the two strings and checks
#: them; it never interprets them.
REFERENCE_COMMIT = "71a513b"
REFERENCE_MANIFEST = "c0ffee42deadbeef"

#: Feature 188's five-column shape, spelled here the way a database the
#: 188 store prepared actually holds it — the starting state the guarded
#: rebuild has to evolve without losing a row.
_LEGACY_DDL = f"""
CREATE TABLE {POOL_TABLE} (
    world_id    TEXT    NOT NULL PRIMARY KEY,
    seed        INTEGER NOT NULL UNIQUE,
    domain      TEXT    NOT NULL,
    pool_seed   INTEGER NOT NULL,
    created_at  TEXT    NOT NULL
)
"""


def a_ported_world(
    world_id: str = "bootstrap-ported-maze",
    *,
    source_commit: str = REFERENCE_COMMIT,
    dataset_manifest: str = REFERENCE_MANIFEST,
) -> Any:
    """A ported world over §10.6.1's reference source, at the digests named.

    The label function is a constant on purpose: feature 191's store
    never reads it (a ported row is an identity, not a cache), so the
    only values that can distinguish one of these worlds from another
    are the ones the row holds — the id and the two digests.
    """
    return ported_world(
        label_fn=lambda node_id: 0.25,
        world_id=world_id,
        provenance=Provenance(
            source_commit=source_commit,
            dataset_manifest=dataset_manifest,
        ),
    )


def the_reference_upstream() -> Provenance:
    """The upstream as a caller positioned at it would read it now."""
    return Provenance(
        source_commit=REFERENCE_COMMIT, dataset_manifest=REFERENCE_MANIFEST
    )


# -- The seating -------------------------------------------------------------------


def test_persisting_a_ported_world_records_its_two_digests(
    pool: BootstrapPool,
) -> None:
    # The write half of the sentence, clause by clause: the source
    # commit and the dataset manifest are what gets persisted — the two
    # §10.6.1 asks a ported world to carry, and nothing else is.
    record = pool.persist_ported_world(a_ported_world())
    assert isinstance(record, PortedWorldRecord)
    assert record.world_id == "bootstrap-ported-maze"
    assert record.source_commit == REFERENCE_COMMIT
    assert record.dataset_manifest == REFERENCE_MANIFEST
    assert record.domain == PORTED_DOMAIN
    assert record.created_at.tzinfo is not None


def test_a_ported_row_seats_no_seed_and_no_draw(
    pool: BootstrapPool, database_url: str
) -> None:
    # A ported world's identity is its upstream, not a draw this member
    # made, so the row's authored-half columns are honestly empty rather
    # than filled with a stand-in — a faked seed would be a ported world
    # wearing an authored world's identity, the exact confusion the
    # table's either-or exists to prevent.  Pinned against the raw row,
    # not the record, because the store is what must not write it.
    pool.persist_ported_world(a_ported_world())
    with sqlite3.connect(database_url.removeprefix("sqlite:///")) as connection:
        row = connection.execute(
            f"SELECT seed, domain, pool_seed, source_commit, dataset_manifest "
            f"FROM {POOL_TABLE}"
        ).fetchone()
    assert row == (
        None,
        PORTED_DOMAIN,
        None,
        REFERENCE_COMMIT,
        REFERENCE_MANIFEST,
    )


def test_the_record_reads_back_as_the_provenance_persisted(
    pool: BootstrapPool,
) -> None:
    # The record's two text columns come back as the frozen value the
    # world was identified by, so a caller holding a record and a caller
    # holding a world compare the same thing — the row and the adapter
    # cannot drift apart in what they mean by "the upstream".
    world = a_ported_world()
    record = pool.persist_ported_world(world)
    assert record.provenance == world.provenance
    assert pool.ported_worlds() == (record,)


def test_the_seating_survives_its_own_process(database_url: str) -> None:
    # The clause every persistence claim turns on: a second store over
    # the same database — the shape of the replay engine's next process —
    # reads the same digests back, which is the difference between a
    # pool row and a cache entry.
    author = BootstrapPool(database_url)
    record = author.persist_ported_world(a_ported_world())
    reader = BootstrapPool(database_url)
    assert reader.ported_worlds() == (record,)
    assert reader.verify_ported_world(record.world_id, the_reference_upstream())


def test_a_re_port_of_the_same_upstream_is_the_same_world(
    pool: BootstrapPool,
) -> None:
    # §10.6.1's rule from the happy side: an upstream that did *not*
    # change is not an updated world either.  One row, answered from the
    # row's own first seating instant — the same created_at discipline a
    # re-run of the authored draw gets, for the same reason.
    first_instant = dt.datetime(2026, 9, 22, 12, 0, 0, tzinfo=dt.UTC)
    later_instant = dt.datetime(2026, 10, 1, 9, 30, 0, tzinfo=dt.UTC)
    first = pool.persist_ported_world(a_ported_world(), persisted_at=first_instant)
    again = pool.persist_ported_world(a_ported_world(), persisted_at=later_instant)
    assert again == first
    assert pool.ported_worlds() == (first,)
    assert pool.ported_worlds()[0].created_at == first_instant


# -- The refusal (§10.6.1) ---------------------------------------------------------


def test_a_changed_source_commit_cannot_take_the_worlds_name(
    pool: BootstrapPool,
) -> None:
    # The refusal the feature exists to make, on the commit half: the
    # upstream's code moved, and a world seated at the old commit cannot
    # answer for labels the new code never earned.  The message names
    # both halves of both upstreams, so an operator reading it can see
    # which half moved.
    pool.persist_ported_world(a_ported_world())
    with pytest.raises(
        BootstrapWorldError, match="recorded against a different upstream"
    ):
        pool.persist_ported_world(a_ported_world(source_commit="ffffffff"))
    with pytest.raises(BootstrapWorldError, match="presented source_commit 'ffffffff'"):
        pool.persist_ported_world(a_ported_world(source_commit="ffffffff"))


def test_a_changed_dataset_manifest_cannot_take_the_worlds_name(
    pool: BootstrapPool,
) -> None:
    # And on the manifest half: the data the labels were ported from
    # changed under the same code, which §10.6.1 treats identically —
    # the failure table lists the two digests as one condition
    # ("dataset_manifest_hash or source_commit mismatch").
    pool.persist_ported_world(a_ported_world())
    with pytest.raises(BootstrapWorldError, match="different upstream"):
        pool.persist_ported_world(a_ported_world(dataset_manifest="0badf00d"))


def test_the_refusal_leaves_the_recorded_row_untouched(
    pool: BootstrapPool,
) -> None:
    # "Refuse it, do not re-hash it into the existing pool" — the row
    # after two refused re-ports is the row before them, digests and
    # all.  A store that refused loudly and then updated anyway would
    # have the worst of both halves.
    pool.persist_ported_world(a_ported_world())
    for moved in (
        a_ported_world(source_commit="ffffffff"),
        a_ported_world(dataset_manifest="0badf00d"),
    ):
        with pytest.raises(BootstrapWorldError):
            pool.persist_ported_world(moved)
    (record,) = pool.ported_worlds()
    assert record.source_commit == REFERENCE_COMMIT
    assert record.dataset_manifest == REFERENCE_MANIFEST
    assert pool.world_count() == 1


def test_a_changed_upstream_under_its_own_name_is_a_new_world(
    pool: BootstrapPool,
) -> None:
    # The one legal move the refusal leaves: a changed upstream is *a
    # different world*, so it seats under its own id and the pool holds
    # both — the old world's labels did not expire when the upstream
    # moved, they just stopped being reachable under the new digests.
    pool.persist_ported_world(a_ported_world())
    pool.persist_ported_world(
        a_ported_world("bootstrap-ported-maze-v2", source_commit="ffffffff")
    )
    first, second = pool.ported_worlds()
    assert first.world_id == "bootstrap-ported-maze"
    assert second.world_id == "bootstrap-ported-maze-v2"
    assert second.source_commit == "ffffffff"
    assert pool.world_count() == 2


def test_a_ported_world_cannot_take_an_authored_worlds_name(
    pool: BootstrapPool,
) -> None:
    # One name is one world, whichever half named it first: an authored
    # row answering a ported ask would answer labels it never recorded,
    # the same attribution failure a misspelled world id invites.
    pool.persist_worlds()
    authored_id = pool.worlds()[0].world_id
    with pytest.raises(BootstrapPoolError, match="authored world"):
        pool.persist_ported_world(a_ported_world(authored_id))


# -- The upstream check -------------------------------------------------------------


def test_the_upstream_check_admits_the_upstream_it_recorded(
    pool: BootstrapPool,
) -> None:
    # The check's happy path: the digests a caller reads off the
    # upstream today are the digests the row recorded, the world is the
    # one it claims to be, and the record answers — which is what lets a
    # replay attribute scores to it.
    record = pool.persist_ported_world(a_ported_world())
    admitted = pool.verify_ported_world(record.world_id, the_reference_upstream())
    assert admitted == record


def test_the_upstream_check_refuses_a_changed_upstream(
    pool: BootstrapPool,
) -> None:
    # The check's refusal, on both halves of the pair: the row's
    # recorded digests are the truth and the presented ones the
    # suspicion, not the other way round — a caller cannot talk the pool
    # into re-hashing a world by presenting newer digests.
    record = pool.persist_ported_world(a_ported_world())
    for upstream in (
        Provenance(source_commit="ffffffff", dataset_manifest=REFERENCE_MANIFEST),
        Provenance(source_commit=REFERENCE_COMMIT, dataset_manifest="0badf00d"),
    ):
        with pytest.raises(BootstrapWorldError, match="refuses the world"):
            pool.verify_ported_world(record.world_id, upstream)


def test_the_upstream_check_refuses_a_world_the_pool_does_not_hold(
    pool: BootstrapPool,
) -> None:
    # A world id the pool never seated is nothing to check: the refusal
    # names it and the count the pool does hold, so a misspelling reads
    # as one rather than as a verdict about an upstream.
    with pytest.raises(BootstrapPoolError, match="holds no world"):
        pool.verify_ported_world("bootstrap-ported-elsewhere", the_reference_upstream())


def test_the_upstream_check_refuses_an_authored_world(
    pool: BootstrapPool,
) -> None:
    # The ask was never about a ported world: an authored row has no
    # digests to compare, and a check that answered for it would be
    # admitting a world on evidence the row does not hold.
    pool.persist_worlds()
    authored_id = pool.worlds()[0].world_id
    with pytest.raises(BootstrapPoolError, match="authored world"):
        pool.verify_ported_world(authored_id, the_reference_upstream())


@pytest.mark.parametrize("bad_id", ["", "   "])
def test_an_unusable_id_is_refused_before_the_check(
    pool: BootstrapPool, bad_id: str
) -> None:
    # Not even reached for: an id that cannot name anything is refused
    # before the database is opened — the same guard every read of this
    # store applies.
    with pytest.raises(BootstrapPoolError, match="non-empty string"):
        pool.verify_ported_world(bad_id, the_reference_upstream())


def test_an_upstream_that_is_not_a_provenance_is_refused(
    pool: BootstrapPool,
) -> None:
    # The check compares two digests against two digests; a caller that
    # hands it anything else has not named an upstream either side of
    # that comparison could read.
    with pytest.raises(BootstrapWorldError, match="named by its digests"):
        pool.verify_ported_world(
            "bootstrap-ported-maze",  # type: ignore[arg-type]
            ("71a513b", "c0ffee42deadbeef"),
        )


# -- The two halves of one pool ------------------------------------------------------


def test_one_pool_holds_both_halves_and_counts_them_together(
    pool: BootstrapPool,
) -> None:
    # §10.6 counts *worlds* — "Authored worlds and ported external
    # worlds both qualify" — so the pool's size is both halves together,
    # while each half is read by the record type it is made of: a seed
    # identity for the authored rows, a digest identity for the ported
    # ones.
    pool.persist_worlds()
    pool.persist_ported_world(a_ported_world())
    authored = pool.worlds()
    assert len(authored) == 45
    assert all(record.seed is not None for record in authored)
    assert len(pool.ported_worlds()) == 1
    assert pool.world_count() == 46


def test_the_authored_read_refuses_a_ported_worlds_id(
    pool: BootstrapPool,
) -> None:
    # The replay engine's read builds a HyperparameterWorld from a seed;
    # a ported row holds none, and the refusal says where the ported
    # half is read instead rather than serving something built from
    # nothing.
    record = pool.persist_ported_world(a_ported_world())
    with pytest.raises(BootstrapPoolError, match="ported world of the pool"):
        pool.world(record.world_id)


def test_ported_worlds_is_ordered_by_world_id(pool: BootstrapPool) -> None:
    # §12's ordering rule, restated for the ported half: two reads of
    # one pool return the same sequence whatever the storage engine's
    # accident, and a report naming both halves reads one order.
    pool.persist_ported_world(a_ported_world("bootstrap-ported-maze"))
    pool.persist_ported_world(a_ported_world("bootstrap-ported-nav"))
    pool.persist_ported_world(a_ported_world("bootstrap-ported-symreg"))
    records = pool.ported_worlds()
    assert [record.world_id for record in records] == sorted(
        record.world_id for record in records
    )
    assert records == pool.ported_worlds()


# -- The table's own shape -----------------------------------------------------------


def test_the_digest_columns_are_the_ones_provenance_rows_key(
    pool: BootstrapPool, database_url: str
) -> None:
    # The promise :meth:`Provenance.row` makes — "keyed by the column
    # names feature 191 records them under" — held from the other side:
    # the table carries exactly the keys the value emits, so the record
    # and the row cannot drift.
    pool.ensure_schema()
    with sqlite3.connect(database_url.removeprefix("sqlite:///")) as connection:
        columns = {str(row[1]) for row in connection.execute(f"PRAGMA table_info({POOL_TABLE})")}
    row_keys = set(the_reference_upstream().row())
    assert row_keys == {"source_commit", "dataset_manifest"}
    assert row_keys <= columns


@pytest.mark.parametrize(
    ("seed", "domain", "source_commit", "dataset_manifest"),
    [
        (None, "ported", None, None),  # neither half: no seed, no digests
        (123, "hpo", "c0ffee", "deadbeef"),  # both halves at once
        (123, PORTED_DOMAIN, None, None),  # an authored row wearing the ported domain
        (None, "ported", "", "deadbeef"),  # a blank digest names no upstream
        (None, "hpo", "c0ffee", "deadbeef"),  # digests that do not declare the domain
    ],
)
def test_the_table_refuses_a_row_that_is_neither_half_nor_the_other(
    pool: BootstrapPool,
    database_url: str,
    seed: int | None,
    domain: str,
    source_commit: str | None,
    dataset_manifest: str | None,
) -> None:
    # The either-or is the table's own voice, not a convention of this
    # module's writers: a row that is not cleanly one half or the other
    # is refused by the CHECK on insert, even by a hand that reached
    # past the store — which is what makes a corrupted pool row refuse
    # itself instead of sitting there being read.
    pool.ensure_schema()
    with (
        pytest.raises(sqlite3.IntegrityError),
        sqlite3.connect(database_url.removeprefix("sqlite:///")) as connection,
    ):
        connection.execute(
            f"INSERT INTO {POOL_TABLE} (world_id, seed, domain, pool_seed, "
            "created_at, source_commit, dataset_manifest) VALUES "
            "('an-impostor', ?, ?, 1, '2026-09-22T00:00:00Z', ?, ?)",
            (seed, domain, source_commit, dataset_manifest),
        )
        connection.commit()


# -- The record, as a value ------------------------------------------------------------


def test_the_record_is_an_identity_value() -> None:
    # The digests are the identity, so equality and hash speak them —
    # not the stamp, which is history, and not the domain, which every
    # ported row carries.  A report may seat the same upstream twice
    # under one name and read one record back.
    seated = dt.datetime(2026, 9, 22, 12, 0, 0, tzinfo=dt.UTC)
    record = PortedWorldRecord(
        world_id="bootstrap-ported-maze",
        source_commit=REFERENCE_COMMIT,
        dataset_manifest=REFERENCE_MANIFEST,
        created_at=seated,
    )
    twin = PortedWorldRecord(
        world_id="bootstrap-ported-maze",
        source_commit=REFERENCE_COMMIT,
        dataset_manifest=REFERENCE_MANIFEST,
        created_at=dt.datetime(2026, 10, 1, tzinfo=dt.UTC),
    )
    other_upstream = PortedWorldRecord(
        world_id="bootstrap-ported-maze",
        source_commit="ffffffff",
        dataset_manifest=REFERENCE_MANIFEST,
        created_at=seated,
    )
    assert record == twin
    assert hash(record) == hash(twin)
    assert record != other_upstream


def test_the_records_row_is_the_full_widened_row() -> None:
    # Both halves' spelling: the digests present, the seed and the draw
    # honestly None — a fresh dict per call, the way a store-shaped
    # mapping always is.
    record = PortedWorldRecord(
        world_id="bootstrap-ported-maze",
        source_commit=REFERENCE_COMMIT,
        dataset_manifest=REFERENCE_MANIFEST,
        created_at=dt.datetime(2026, 9, 22, 12, 34, 56, tzinfo=dt.UTC),
    )
    assert record.row() == {
        "world_id": "bootstrap-ported-maze",
        "seed": None,
        "domain": PORTED_DOMAIN,
        "pool_seed": None,
        "created_at": "2026-09-22T12:34:56Z",
        "source_commit": REFERENCE_COMMIT,
        "dataset_manifest": REFERENCE_MANIFEST,
    }
    assert record.row() is not record.row()


def test_a_record_refuses_a_blank_digest() -> None:
    # The same guard Provenance applies, on the read-back side of the
    # row: a record holding a blank digest could not be checked against
    # the upstream it claims, so it is refused by name at construction.
    with pytest.raises(BootstrapWorldError, match="dataset_manifest"):
        PortedWorldRecord(
            world_id="bootstrap-ported-maze",
            source_commit=REFERENCE_COMMIT,
            dataset_manifest="   ",
            created_at=dt.datetime(2026, 9, 22, tzinfo=dt.UTC),
        )


# -- The seating's own guards -----------------------------------------------------------


def test_persisting_a_world_that_cannot_name_itself_is_refused(
    pool: BootstrapPool,
) -> None:
    # The two facts a row is made of, refused before the database is
    # opened: an object with no world_id records nothing the pool could
    # verify against an upstream.
    with pytest.raises(BootstrapPoolError, match="under its id"):
        pool.persist_ported_world(object())


def test_persisting_a_world_without_provenance_is_refused(
    pool: BootstrapPool,
) -> None:
    # And an object that names a world but carries no digests has no
    # upstream a re-port could be checked against — the adapter's own
    # constructor guard, restated at the store's door for whatever
    # duck-typed thing reaches it.
    class Foreign:
        world_id = "bootstrap-ported-foreign"

    with pytest.raises(BootstrapWorldError, match="carries its provenance"):
        pool.persist_ported_world(Foreign())


# -- The legacy pool -------------------------------------------------------------------


def test_a_legacy_pool_is_evolved_its_authored_rows_kept(
    database_url: str,
) -> None:
    # A database feature 188's store prepared is the 188 shape, and the
    # widened pool owes it evolution rather than abandonment: the
    # ported seating works against it, every authored row survives with
    # its identity intact, and the shape it lands in is the widened one
    # — after which the evolution is a no-op, the same idempotence
    # ensure_schema always promised.
    path = database_url.removeprefix("sqlite:///")
    with sqlite3.connect(path) as connection:
        connection.execute(_LEGACY_DDL)
        connection.execute(
            f"INSERT INTO {POOL_TABLE} (world_id, seed, domain, pool_seed, "
            "created_at) VALUES ('bootstrap-hpo-20260922-00', 12345, 'hpo', "
            "20260922, '2026-09-22T00:00:00Z')"
        )
        connection.commit()
    pool = BootstrapPool(database_url)
    record = pool.persist_ported_world(a_ported_world())
    assert pool.world_count() == 2
    (authored,) = pool.worlds()
    assert authored.world_id == "bootstrap-hpo-20260922-00"
    assert authored.seed == 12345
    assert authored.domain == "hpo"
    pool.ensure_schema()
    assert pool.ported_worlds() == (record,)
    with sqlite3.connect(path) as connection:
        columns = [str(row[1]) for row in connection.execute(f"PRAGMA table_info({POOL_TABLE})")]
    assert "source_commit" in columns
    assert "dataset_manifest" in columns


def test_the_authored_draw_still_runs_on_an_evolved_pool(
    database_url: str,
) -> None:
    # The evolution must not cost the authored half its own path: the
    # draw, the upsert and the reads all run against the rebuilt table
    # exactly as they ran against the original one.
    path = database_url.removeprefix("sqlite:///")
    with sqlite3.connect(path) as connection:
        connection.execute(_LEGACY_DDL)
        connection.commit()
    pool = BootstrapPool(database_url)
    report = pool.persist_worlds()
    assert report.count == 45
    assert pool.world_count() == 45
    assert pool.worlds()[0].seed == report.worlds[0].seed
