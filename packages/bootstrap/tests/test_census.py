"""Feature 186 — the two pools' sizes, tracked and returned separately.

app_spec.xml, "Bootstrap Worlds", feature 186: *System tracks financial
world count independently from bootstrap world count, which returns both
figures separately.*  This suite holds the census to the sentence the way
the member's other suites hold theirs — clause by clause, from the
documented side:

* **"tracks financial world count"** — the financial figure counts the
  stored worlds the replay pool holds and the bootstrap pool does not,
  read from ``replay_score`` (migration ``0109``'s table, whose
  ``world_id`` column is the whole join).  *Distinct*, because a row is
  one *(policy, world)* pair and §10.3.1 replays every revision against
  every world — a plain ``COUNT`` would grow with every dreaming cycle.
* **"independently from bootstrap world count"** — the two figures come
  from two reads over one database, not from one figure and a caller's
  arithmetic, and the exclusion between them is enforced: a world id the
  bootstrap pool holds is *never* counted as financial, which is the
  clause §10.6.1 states as *"it pads ``n``, never ``n_financial``"*.
  Both directions are pinned: seating ported and authored worlds raises
  ``n_bootstrap`` and leaves ``n_financial`` exactly where it was.
* **"returns both figures separately"** — :meth:`WorldCensus.row` hands
  a report the two figures and nothing else, and
  :attr:`WorldCensus.total` is documented as §12.1's ladder reading so
  the one mixed number is reachable only by a caller who asked for it by
  name.

Beside the clause-by-clause claims sit the store's own guards — the
absent ``replay_score`` table that must refuse rather than answer a zero,
the object that is not a pool, a pool whose own count is not a size, the
hand-built census with an impossible figure — each pinned by the error it
raises and the subject it names, the discipline every store suite in this
workspace follows.
"""

from __future__ import annotations

import sqlite3

import pytest
from bootstrap import (
    MIN_POOL_SIZE,
    POOL_TABLE,
    BootstrapPool,
    BootstrapPoolError,
    Provenance,
    WorldCensus,
    ported_world,
    world_census,
)

#: ``0109``'s ``replay_score`` columns, in the migration's order — spelled
#: here rather than imported from the member, because the census *reads* a
#: table it does not own and the suite seeds one the way ``0109`` declares
#: it.  A convenience shape would let the census's tests pass against a
#: table the system does not have.
_SCORE_COLUMNS = (
    "id, policy_version, world_id, beta, score, committed_pick, is_holdout, created_at"
)

#: A world id in the vocabulary a financial campaign's world actually uses
#: — a UUID, per ``0109``'s ``world_id UUID NOT NULL``.  Nothing in the
#: census reads it as an id *shape*; it is written this way so the tests
#: cannot pass by accident on a prefix rule the module deliberately does
#: not implement.
_FINANCIAL_WORLD = "7c1e6a48-0b93-4d2f-9a51-3e8f0d6b2c74"

#: The DDL ``0109`` creates, in the shape the census reads it.  A database
#: the migration has not reached yet is a real state this feature refuses
#: (``test_a_database_without_a_replay_pool_is_refused``), so the suite
#: creates the table itself for every test that *does* have a replay pool.
_REPLAY_SCORE_DDL = """
CREATE TABLE IF NOT EXISTS replay_score (
    id             TEXT NOT NULL PRIMARY KEY,
    policy_version TEXT NOT NULL,
    world_id       TEXT NOT NULL,
    beta           REAL NOT NULL,
    score          REAL NOT NULL,
    committed_pick TEXT,
    is_holdout     BOOLEAN NOT NULL DEFAULT FALSE,
    created_at     TEXT NOT NULL
)
"""


def _seed_score(
    database_url: str,
    *,
    world_id: str,
    policy_version: str = "policy-v1",
    score_id: str | None = None,
) -> None:
    """Write one ``replay_score`` row, the way the replay member would.

    The rows are written straight into the table rather than through a
    store, because no store for the pool exists in this member — the
    replay member (features 245-255) is its writer, and this suite is
    about the *read*.  Every column the migration declares is supplied, so
    a row here is a row the migration would accept.
    """
    with sqlite3.connect(_path_of(database_url)) as connection:
        connection.executescript(_REPLAY_SCORE_DDL)
        connection.execute(
            f"INSERT INTO replay_score ({_SCORE_COLUMNS}) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                score_id or f"score-{world_id}-{policy_version}",
                policy_version,
                world_id,
                1.0,
                0.5,
                None,
                False,
                "2026-09-22T00:00:00Z",
            ),
        )


def _path_of(database_url: str) -> str:
    """The filesystem path a ``sqlite:///`` URL names."""
    return database_url.removeprefix("sqlite:///")


def _seed_replay_pool(database_url: str) -> None:
    """Create the ``replay_score`` table with no rows in it.

    The *migrated, nothing scored yet* state — a deployment that has run
    the migration and not yet replayed a policy.  It is a real state with
    a real answer (zero financial worlds), and telling it apart from the
    unmigrated state is half of what the absent-table refusal is for.
    """
    with sqlite3.connect(_path_of(database_url)) as connection:
        connection.executescript(_REPLAY_SCORE_DDL)


# -- The financial figure ------------------------------------------------------------


def test_the_financial_figure_counts_the_worlds_the_pool_scored(
    pool: BootstrapPool, database_url: str
) -> None:
    # The plain case: worlds recorded in the replay pool and held by no
    # bootstrap row are financial worlds, and the census reports how many
    # there are.  The bootstrap half is empty here, so the two figures are
    # told apart by the count alone.
    _seed_score(database_url, world_id=_FINANCIAL_WORLD)
    census = world_census(pool)
    assert census.n_financial == 1
    assert census.n_bootstrap == 0


def test_one_world_replayed_by_many_policies_is_counted_once(
    pool: BootstrapPool, database_url: str
) -> None:
    # §10.3.1 evaluates *every* candidate revision against *every* stored
    # world, so one world leaves one row per revision.  A plain COUNT over
    # the pool would report a world once per policy and the figure would
    # grow every time the dreaming loop ran — a pool size that measured
    # the loop rather than the pool.
    for revision in ("policy-v1", "policy-v2", "policy-v3"):
        _seed_score(database_url, world_id=_FINANCIAL_WORLD, policy_version=revision)
    census = world_census(pool)
    assert census.n_financial == 1


def test_several_financial_worlds_are_counted_apart(
    pool: BootstrapPool, database_url: str
) -> None:
    # Two worlds, one of them replayed twice: the figure is the number of
    # *worlds* the pool holds, which is what §10.3.1's ``n_worlds`` means.
    _seed_score(database_url, world_id=_FINANCIAL_WORLD)
    _seed_score(database_url, world_id=_FINANCIAL_WORLD, policy_version="policy-v2")
    _seed_score(database_url, world_id="5b0c9d17-2f4a-4e83-b6c1-8d72a0e5f934")
    census = world_census(pool)
    assert census.n_financial == 2


def test_an_empty_replay_pool_is_zero_and_not_an_error(
    pool: BootstrapPool, database_url: str
) -> None:
    # A migrated deployment that has not replayed anything holds zero
    # financial worlds.  That is a *measured* zero — the table is there
    # and it says nothing — and it is a different fact from a database
    # with no replay pool at all, which the refusal below covers.
    _seed_replay_pool(database_url)
    census = world_census(pool)
    assert census.n_financial == 0
    assert census.n_bootstrap == 0


# -- The independence ----------------------------------------------------------------


def test_bootstrap_worlds_raise_n_but_never_n_financial(
    pool: BootstrapPool, database_url: str
) -> None:
    # §10.6.1's one sentence about counting, pinned in both figures at
    # once: the worlds this category authors *pad n* — the total a ladder
    # reads — and leave ``n_financial`` exactly where it was.  45
    # generated hyperparameter-search worlds are not 45 crypto campaigns,
    # and the M3 gate is evaluated on financial worlds only.
    _seed_score(database_url, world_id=_FINANCIAL_WORLD)
    before = world_census(pool)
    pool.persist_worlds(MIN_POOL_SIZE)
    after = world_census(pool)

    assert before.n_financial == after.n_financial == 1
    assert after.n_bootstrap == MIN_POOL_SIZE
    assert after.total == before.total + MIN_POOL_SIZE


def test_a_replay_against_a_bootstrap_world_stays_out_of_the_financial_figure(
    pool: BootstrapPool, database_url: str
) -> None:
    # The sharpest form of the exclusion, and the state the dreaming loop
    # actually produces: the loop replays policies *against the bootstrap
    # pool*, so ``replay_score`` holds rows whose ``world_id`` is a
    # bootstrap world.  A census that counted every world id it saw would
    # report 45 financial worlds the moment the loop first ran — the
    # precise inversion of §10.6.1's rule, and a number that would admit
    # the M3 gate on bootstrap evidence.
    report = pool.persist_worlds(MIN_POOL_SIZE)
    for record in report.worlds:
        _seed_score(database_url, world_id=record.world_id)
    _seed_score(database_url, world_id=_FINANCIAL_WORLD)

    census = world_census(pool)
    assert census.n_financial == 1
    assert census.n_bootstrap == MIN_POOL_SIZE


def test_a_ported_world_pads_the_bootstrap_figure_and_not_the_financial_one(
    pool: BootstrapPool, database_url: str
) -> None:
    # §10.6 is explicit that *"Authored worlds and ported external worlds
    # both qualify"* for padding ``n``, and §10.6.1 is explicit that the
    # padding never reaches ``n_financial`` — so a ported row raises the
    # bootstrap figure with no seed, no draw and no change to the
    # financial one.
    pool.persist_worlds(MIN_POOL_SIZE)
    pool.persist_ported_world(
        ported_world(
            label_fn=lambda node_id: 0.25,
            world_id="bootstrap-ported-maze",
            provenance=Provenance(
                source_commit="71a513b", dataset_manifest="c0ffee42deadbeef"
            ),
        )
    )
    _seed_score(database_url, world_id=_FINANCIAL_WORLD)

    census = world_census(pool)
    assert census.n_bootstrap == MIN_POOL_SIZE + 1
    assert census.n_financial == 1


def test_the_financial_figure_is_taken_from_the_pools_own_database(
    pool: BootstrapPool, database_url: str, tmp_path_factory: pytest.TempPathFactory
) -> None:
    # "Independently" is a property of the two reads: both figures come
    # out of the one database the pool resolves, which is the database
    # feature 188 chose so that *"persists into the replay pool"* is a
    # statement about the pool the dreaming loop reads.  A census that
    # read its financial figure from somewhere else — an environment
    # variable, a second connection string — would be comparable in
    # appearance only.  Proven here by putting a financial world in a
    # *different* database and showing the census does not see it.
    elsewhere = tmp_path_factory.mktemp("elsewhere") / "other.db"
    _seed_score(f"sqlite:///{elsewhere}", world_id=_FINANCIAL_WORLD)
    _seed_score(database_url, world_id="5b0c9d17-2f4a-4e83-b6c1-8d72a0e5f934")

    census = world_census(pool)
    assert census.n_financial == 1  # the world in the pool's database


def test_the_census_is_a_pure_read(
    pool: BootstrapPool, database_url: str
) -> None:
    # Taking a census must not change what the next census reports: the
    # read writes no row to either table, so an operator may ask as often
    # as they like — and a census that appended would make §10.3.1's
    # precondition depend on how many times it had been checked.
    _seed_score(database_url, world_id=_FINANCIAL_WORLD)
    pool.persist_worlds(MIN_POOL_SIZE)
    first = world_census(pool)
    second = world_census(pool)
    assert first == second
    assert pool.world_count() == MIN_POOL_SIZE
    with sqlite3.connect(_path_of(database_url)) as connection:
        (held,) = connection.execute(
            f"SELECT COUNT(*) FROM {POOL_TABLE}"
        ).fetchone()
    assert held == MIN_POOL_SIZE


# -- The two figures, and the one that is not a third --------------------------------


def test_the_row_hands_a_report_both_figures_and_nothing_else() -> None:
    # The feature's own word is *separately*, and the row is where
    # "separately" is delivered: exactly two keys, one per pool.  The
    # total is deliberately absent even though it is one addition away —
    # a report that wrote a mixed count beside the two would be a third
    # number for a reader to reach for, and the reader who reached for it
    # is the one §10.6 warns about.
    census = WorldCensus(n_financial=7, n_bootstrap=45)
    assert census.row() == {"n_financial": 7, "n_bootstrap": 45}


def test_the_row_hands_out_a_fresh_dict_per_call() -> None:
    # A caller annotating the row it was handed must not be annotating
    # every other caller's — the discipline the world's ``Observation``,
    # the question's ``CellMeta`` and the truth's ``GroundTruth`` all take.
    census = WorldCensus(n_financial=1, n_bootstrap=2)
    assert census.row() is not census.row()


def test_the_total_is_the_ladder_reading_and_not_the_gate_figure() -> None:
    # §12.1's ladder counts *worlds* — "below 20", "between 20 and 50" —
    # so the sum exists and is a real figure with one reader.  It is
    # emphatically not what §10.6's M3 gate reads: the gate is evaluated
    # on financial holdout worlds only.  The property is pinned so a later
    # edit that renamed or removed it would be a deliberate act rather
    # than a silent drift.
    census = WorldCensus(n_financial=7, n_bootstrap=45)
    assert census.total == 52


def test_the_census_is_frozen_and_equal_by_its_two_fields() -> None:
    # A census is a *measurement*: two callers holding one hold the same
    # pair of numbers, and a re-taken census over an unchanged pool is the
    # same value a report can compare.
    import dataclasses

    assert WorldCensus(1, 2) == WorldCensus(n_financial=1, n_bootstrap=2)
    with pytest.raises(dataclasses.FrozenInstanceError):
        WorldCensus(1, 2).n_financial = 3  # type: ignore[misc]


# -- The refusals --------------------------------------------------------------------


@pytest.mark.parametrize("bad", [-1, True, "45", 1.5, None])
@pytest.mark.parametrize("field", ["n_financial", "n_bootstrap"])
def test_a_figure_that_is_not_a_pool_size_is_refused(
    field: str, bad: object
) -> None:
    # A hand-built census is a test's prerogative, but a figure that is
    # not a non-negative whole number is a pool size no read could
    # produce — and both figures reach §12.1's ladder, which blocks or
    # admits a dreaming cycle on them.  ``True`` is refused where a count
    # belongs for the reason the member refuses one on an axis: it is
    # ``1`` in Python, so a flag would silently report a pool of one.
    other = "n_bootstrap" if field == "n_financial" else "n_financial"
    with pytest.raises(BootstrapPoolError, match=field):
        WorldCensus(**{field: bad, other: 0})  # type: ignore[arg-type]


def test_a_database_without_a_replay_pool_is_refused(
    database_url: str,
) -> None:
    # A database with no ``replay_score`` table has no replay pool in it.
    # Answering zero would be inventing a pool size, and here that is
    # sharper than usual: ``n_financial = 0`` is a *blocking* answer —
    # §12.1's ladder refuses to dream below 20 worlds — so a mis-pointed
    # database would halt dreaming on a number this member made up rather
    # than on a refusal an operator can read.
    pool = BootstrapPool(database_url)  # no replay_score table is created
    with pytest.raises(BootstrapPoolError, match="replay_score") as refusal:
        world_census(pool)
    assert _path_of(database_url) in str(refusal.value)


@pytest.mark.parametrize("not_a_pool", ["a pool", 45, {"world_count": 3}, None])
def test_an_object_that_is_not_a_pool_is_refused(not_a_pool: object) -> None:
    # The census duck-types the pool rather than ``isinstance``-ing it —
    # the module loader hands out a second copy of the class under a
    # synthetic name — so an object missing the surface it calls through
    # is refused naming what was missing, before anything touches a disk.
    with pytest.raises(BootstrapPoolError):
        world_census(not_a_pool)


def test_a_pool_whose_count_is_not_a_size_is_refused() -> None:
    # A duck-typed pool is a caller's object, not this member's: a
    # ``world_count`` that returned ``None``, a string or a flag would put
    # a value the census cannot vouch for into a figure §12.1's ladder
    # blocks dreaming on.  Refused rather than coerced.
    class Sloppy:
        path = ":memory:"

        def world_count(self) -> object:
            return "45"

    with pytest.raises(BootstrapPoolError, match="non-negative whole number"):
        world_census(Sloppy())


def test_a_url_the_store_cannot_speak_is_refused_in_the_pools_own_vocabulary(
    database_url: str,
) -> None:
    # The one refusal the census does *not* translate.  A ``DATABASE_URL``
    # scheme the store cannot speak is the pool's own contract, raised by
    # the pool's own path resolution — the census was handed the pool, and
    # a second spelling of the refusal here would give a caller two
    # ``except`` clauses for one fact.
    pool = BootstrapPool("sqlite://elsewhere:5432/pool.db")
    with pytest.raises(BootstrapPoolError, match="must not carry a host"):
        world_census(pool)
