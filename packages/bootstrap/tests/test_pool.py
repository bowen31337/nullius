"""The bootstrap replay pool — feature 188's authoring, persisted.

app_spec.xml, "Bootstrap Worlds", feature 188: *System persists 40 to 50
generated bootstrap worlds into the replay pool on demand.*  This suite
holds the store to that sentence clause by clause:

* **"40 to 50"** is a band the authoring *refuses* outside rather than
  clamps toward — below it the pool would undercut the target §10.6 sets
  for the first financial dreaming cycle, above it bootstrap worlds
  would dominate the pool's composition — and the band's two edges are
  themselves persistable, because a range whose edges did not hold would
  be a range the message only claimed.
* **"generated"** means the worlds are drawn, and the draw is a pure
  function of ``(pool_seed, index)``: re-running the authoring re-draws
  the *same* worlds (a refresh, not a re-draw), two indices of one draw
  never collide onto one seed, and two different draws author different
  worlds — §10.6.1's *"a different world, not an updated one"*, seen
  from the pool's side.
* **"into the replay pool"** means the rows survive the process that
  wrote them: a second store over the same database reads the same
  worlds back, which is the difference between persisting and caching.
* **"on demand"** means the authoring happens at the call and nowhere
  else — the composition-level half of that claim lives in
  ``test_pool_component.py``; here it is the refresh story (a re-run
  rewrites the same rows, keeps the first authoring instant, and adds
  only the worlds a larger draw actually draws).

Beside the clause-by-clause claims sit the store's own refusals — the
naive instant, the database the store cannot speak, the in-memory
database that would not outlive its own authoring, and the draw that
would seat one world under two names — each pinned by the error it
raises and the subject it names, the discipline every store suite in
this workspace follows.
"""

from __future__ import annotations

import datetime as dt
import sqlite3

import pytest
from bootstrap import (
    MAX_POOL_SIZE,
    MIN_POOL_SIZE,
    POOL_DOMAIN,
    POOL_SEED,
    POOL_TABLE,
    BootstrapPool,
    BootstrapPoolError,
    HyperparameterWorld,
    draw_world_seed,
    world_id_for,
)
from bootstrap._pool import parsed_instant

# -- The band ---------------------------------------------------------------------


def test_a_size_below_the_band_is_refused(pool: BootstrapPool) -> None:
    # §10.6 targets 40-50 bootstrap worlds *before the first financial
    # dreaming cycle*, and §12.1's ladder rates a thinner pool as weaker
    # to dream on — so a short draw is refused, not rounded up.  A store
    # that silently rounded would report a coverage the operator never
    # asked for.
    with pytest.raises(BootstrapPoolError, match=r"40 to 50"):
        pool.persist_worlds(MIN_POOL_SIZE - 1)
    assert pool.world_count() == 0


def test_a_size_above_the_band_is_refused(pool: BootstrapPool) -> None:
    # The high edge is §10.6's own: bootstrap worlds are the *preparation*
    # for fine-tuning on financial worlds, and a pool that grew without
    # bound would let them dominate the composition the fine-tuning is
    # measured against — the imbalance feature 187's headline refusal
    # exists to reject on the reporting side.
    with pytest.raises(BootstrapPoolError, match=r"40 to 50"):
        pool.persist_worlds(MAX_POOL_SIZE + 1)
    assert pool.world_count() == 0


@pytest.mark.parametrize("size", [MIN_POOL_SIZE, MAX_POOL_SIZE])
def test_both_edges_of_the_band_persist(pool: BootstrapPool, size: int) -> None:
    # A band whose edges did not hold would be a band the refusal message
    # only claimed.  Both edges seat exactly the size asked.
    report = pool.persist_worlds(size)
    assert report.count == size
    assert pool.world_count() == size


def test_the_default_size_is_the_band_midpoint(pool: BootstrapPool) -> None:
    # An authoring call that names no size gets 45 — squarely inside the
    # target rather than at either edge of it.
    report = pool.persist_worlds()
    assert report.count == 45
    assert pool.world_count() == 45


@pytest.mark.parametrize("flag", [True, False])
def test_a_flag_where_a_size_belongs_is_refused(
    pool: BootstrapPool, flag: bool
) -> None:
    # ``True`` is ``1`` in Python, so a flag where a size belongs would
    # otherwise ask for a one-world pool (or a zero-world one) — the same
    # trap :class:`~bootstrap.HyperparameterSetting` refuses for its axes.
    with pytest.raises(BootstrapPoolError, match="pool size is an integer"):
        pool.persist_worlds(flag)  # type: ignore[arg-type]


def test_a_non_integer_size_is_refused(pool: BootstrapPool) -> None:
    # ``45.0`` is *nearly* 45, and a store that accepted it would accept
    # ``45.5`` on the same rule — the band is a count of worlds or it is
    # nothing.
    with pytest.raises(BootstrapPoolError, match="pool size is an integer"):
        pool.persist_worlds(45.0)  # type: ignore[arg-type]


def test_a_non_integer_pool_seed_is_refused(pool: BootstrapPool) -> None:
    # The seed is the whole of the draw's identity; a value that is not
    # an integer names no pool this member can re-draw.
    with pytest.raises(BootstrapPoolError, match="pool seed is an integer"):
        pool.persist_worlds(pool_seed=20260922.0)  # type: ignore[arg-type]


# -- The draw ---------------------------------------------------------------------


def test_the_draw_is_a_pure_function_of_pool_seed_and_index() -> None:
    # Same (pool_seed, index) pair, same seed, in any process and any
    # order of calls — the property that makes a re-run of the authoring
    # a refresh rather than a re-draw.
    assert draw_world_seed(POOL_SEED, 0) == draw_world_seed(POOL_SEED, 0)
    assert draw_world_seed(POOL_SEED, 0) != draw_world_seed(POOL_SEED, 1)


def test_two_indices_of_one_draw_never_collide() -> None:
    # mix64 is a bijection over the 64-bit words and the golden-ratio
    # increment is odd, so the stream construction cannot hand two
    # indices of one draw the same seed — a pool that could would seat
    # one world under two names, over-reporting the very size §10.3.1's
    # precondition turns on.
    seeds = [draw_world_seed(POOL_SEED, index) for index in range(MAX_POOL_SIZE)]
    assert len(set(seeds)) == MAX_POOL_SIZE


def test_the_drawn_seeds_stay_inside_the_range_sqlite_holds() -> None:
    # SQLite's INTEGER is a signed 64-bit, so the draw returns its words
    # in the signed spelling — and the world folds either spelling into
    # the same ring, so the constraint costs nothing.  Pinned here
    # because an unsigned draw would cross the storage boundary as an
    # ``OverflowError`` far from its cause.
    for index in range(MAX_POOL_SIZE):
        seed = draw_world_seed(POOL_SEED, index)
        assert -(1 << 63) <= seed <= (1 << 63) - 1, index


def test_the_world_ids_carry_domain_pool_seed_and_index() -> None:
    # ``bootstrap-hpo-20260922-07`` — readable, because §10.6's pool is
    # reported and an operator reading a replay score wants to see which
    # world it came from; and two digits of index, because 50 worlds
    # means indices 0-49 and the ids then sort lexicographically in draw
    # order, which is what makes ``ORDER BY world_id`` the pool's own
    # order.
    assert world_id_for(POOL_SEED, 7) == f"bootstrap-{POOL_DOMAIN}-{POOL_SEED}-07"
    ids = [world_id_for(POOL_SEED, index) for index in range(MAX_POOL_SIZE)]
    assert ids == sorted(ids)


def test_two_draws_author_different_worlds() -> None:
    # §10.6.1's provenance rule from the pool's side: another draw is
    # another pool — different seeds, different names — not a mutation
    # of the first one's rows.
    for index in range(MIN_POOL_SIZE):
        assert draw_world_seed(POOL_SEED, index) != draw_world_seed(POOL_SEED + 1, index)
        assert world_id_for(POOL_SEED, index) != world_id_for(POOL_SEED + 1, index)


# -- The persistence --------------------------------------------------------------


def test_persisting_seats_one_row_per_world(pool: BootstrapPool) -> None:
    # The report and the table agree, and both agree with the ask.
    report = pool.persist_worlds()
    assert report.count == 45
    assert len(report.worlds) == 45
    assert pool.world_count() == 45
    assert len(pool.worlds()) == 45


def test_a_persisted_row_holds_the_identity_the_draw_names(
    pool: BootstrapPool,
) -> None:
    # The row is the identity the draw computed — the id, the seed, the
    # domain and the draw that authored it — and nothing else is stored:
    # a dataset beside them would be a cache of a pure function, and a
    # cache that drifted would be a different world wearing an old
    # world's name.
    pool.persist_worlds()
    records = pool.worlds()
    for index, record in enumerate(records):
        assert record.world_id == world_id_for(POOL_SEED, index)
        assert record.seed == draw_world_seed(POOL_SEED, index)
        assert record.domain == POOL_DOMAIN
        assert record.pool_seed == POOL_SEED


def test_the_pool_survives_its_own_process(database_url: str) -> None:
    # The clause the feature turns on: *persists*.  A second store over
    # the same database — the shape of the replay engine's next process —
    # reads the same worlds back, identity for identity, which is the
    # difference between a pool and a cache.
    author = BootstrapPool(database_url)
    author.persist_worlds()
    reader = BootstrapPool(database_url)
    assert reader.world_count() == 45
    persisted = author.worlds()
    reread = reader.worlds()
    assert reread == persisted


def test_a_rerun_is_a_refresh_not_an_append(pool: BootstrapPool) -> None:
    # Re-authoring the same draw re-draws the same worlds, so the upsert
    # rewrites the same rows: the count does not double, the ids are the
    # ids, and the report says ``replayed`` — the authoring operation is
    # repeatable, which is what makes "on demand" safe to honour twice.
    first = pool.persist_worlds()
    assert not first.replayed
    second = pool.persist_worlds()
    assert second.replayed
    assert pool.world_count() == 45
    assert [record.world_id for record in second.worlds] == [
        record.world_id for record in first.worlds
    ]


def test_a_refresh_keeps_the_worlds_first_authoring_instant(
    pool: BootstrapPool,
) -> None:
    # The same world re-asserted is the same world — §10.6.1: an upstream
    # that changes is a *different* world, so one that did not change is
    # not an updated one either.  The upsert deliberately leaves
    # ``created_at`` alone, and the second call's later instant does not
    # reach it.
    authored = dt.datetime(2026, 9, 22, 12, 0, 0, tzinfo=dt.UTC)
    reasserted = dt.datetime(2026, 10, 1, 9, 30, 0, tzinfo=dt.UTC)
    pool.persist_worlds(persisted_at=authored)
    pool.persist_worlds(persisted_at=reasserted)
    for record in pool.worlds():
        assert record.created_at == authored


def test_a_larger_rerun_adds_only_the_worlds_it_draws(pool: BootstrapPool) -> None:
    # Growing a pool inside one draw seats the new indices and refreshes
    # the old ones — nothing is re-drawn, because the draw is indexed and
    # not sequenced.
    pool.persist_worlds(MIN_POOL_SIZE)
    held = [record.world_id for record in pool.worlds()]
    report = pool.persist_worlds(MIN_POOL_SIZE + 5)
    assert pool.world_count() == MIN_POOL_SIZE + 5
    assert [record.world_id for record in pool.worlds()[:MIN_POOL_SIZE]] == held
    assert report.replayed


def test_a_second_draw_adds_worlds_it_can_name(pool: BootstrapPool) -> None:
    # Two draws in one database are two pools' worth of worlds, each row
    # naming the draw that authored it — the pool does not silently
    # mutate the first draw's rows to hold the second draw's seeds.
    pool.persist_worlds(MIN_POOL_SIZE, pool_seed=POOL_SEED)
    pool.persist_worlds(MIN_POOL_SIZE, pool_seed=POOL_SEED + 1)
    assert pool.world_count() == 2 * MIN_POOL_SIZE
    drawn = {record.pool_seed for record in pool.worlds()}
    assert drawn == {POOL_SEED, POOL_SEED + 1}


def test_one_seed_under_two_names_is_refused(
    pool: BootstrapPool, database_url: str
) -> None:
    # The seed's UNIQUE constraint, translated into the pool's own
    # vocabulary: a row that already holds this seed under a *different*
    # world id is one world seated twice, and the authoring refuses
    # rather than over-reporting the pool's size.  Seeded by hand, because
    # the draw itself cannot produce the collision — and seeded *first*,
    # because once the pool's own row holds the seed, the impostor's
    # insert is the one the constraint refuses.
    pool.ensure_schema()
    stolen_seed = draw_world_seed(POOL_SEED, 0)
    with sqlite3.connect(database_url.removeprefix("sqlite:///")) as connection:
        connection.execute(
            f"INSERT INTO {POOL_TABLE} (world_id, seed, domain, pool_seed, "
            "created_at) VALUES ('bootstrap-hpo-impostor', ?, 'hpo', 1, "
            "'2026-09-22T00:00:00Z')",
            (stolen_seed,),
        )
        connection.commit()
    with pytest.raises(BootstrapPoolError, match="under another world_id"):
        pool.persist_worlds()


# -- The reads --------------------------------------------------------------------


def test_worlds_is_ordered_by_world_id(pool: BootstrapPool) -> None:
    # Explicitly ordered (§12's ordering rule, restated for a store): two
    # reads of one pool return the same sequence whatever the storage
    # engine's accident — and because the ids carry two index digits, the
    # order *is* draw order.
    pool.persist_worlds()
    records = pool.worlds()
    assert [record.world_id for record in records] == sorted(
        record.world_id for record in records
    )
    assert records == pool.worlds()


def test_an_empty_pool_reads_as_zero_and_not_as_an_error(pool: BootstrapPool) -> None:
    # An empty pool is a statement about what has been *authored*, not
    # about composition (the seat's ``None``) — feature 186's count is
    # the caller that reports it against the financial half, and it
    # needs zero to be readable.
    assert pool.world_count() == 0
    assert pool.worlds() == ()


def test_world_builds_the_world_a_row_names(pool: BootstrapPool) -> None:
    # The replay engine's read: a world id in hand, the world that earned
    # the score comes back — built from the row's own seed, so it is the
    # world the row recorded, bit for bit, in any process.
    pool.persist_worlds()
    record = pool.worlds()[3]
    world = pool.world(record.world_id)
    assert type(world) is HyperparameterWorld
    assert world.world_id == record.world_id
    assert world.seed == record.seed
    direct = HyperparameterWorld(record.world_id, seed=record.seed)
    node = world.canonical_node()
    assert world.label(node).r2_holdout == direct.label(node).r2_holdout
    assert world.label(node).coefficients == direct.label(node).coefficients


def test_two_persisted_worlds_answer_different_labels(pool: BootstrapPool) -> None:
    # The point of drawing 40-50 seeds rather than re-using one: each
    # world's data is its own draw (the token translation of
    # ``_feature_cell``), so two worlds of the pool pose two different
    # searches — a pool whose worlds all answered alike would be one
    # world counted 45 times, and §10.3.1's precondition deserves better.
    pool.persist_worlds()
    first, second = pool.worlds()[0], pool.worlds()[1]
    node = pool.world(first.world_id).canonical_node()
    assert (
        pool.world(first.world_id).label(node).r2_holdout
        != pool.world(second.world_id).label(node).r2_holdout
    )


def test_a_world_the_pool_does_not_hold_is_refused(pool: BootstrapPool) -> None:
    # A misspelled id wants a refusal it can read — the id named, the
    # count held — not a world silently served from a neighbouring row:
    # a pool that answered anyway would attribute a score to a world
    # that never earned it.
    pool.persist_worlds()
    with pytest.raises(BootstrapPoolError, match="holds no world"):
        pool.world("bootstrap-hpo-20260922-99")
    with pytest.raises(BootstrapPoolError, match="45 world"):
        pool.world("bootstrap-hpo-20260922-99")


@pytest.mark.parametrize("bad_id", ["", "   "])
def test_an_unusable_world_id_is_refused(pool: BootstrapPool, bad_id: str) -> None:
    # Not even reached for: an id that cannot name anything is refused
    # before the database is opened.
    with pytest.raises(BootstrapPoolError, match="non-empty string"):
        pool.world(bad_id)


# -- The deployment state ---------------------------------------------------------


def test_resolve_reads_the_database_the_environment_names() -> None:
    # The composed pool is the deployment's pool: the URL the
    # environment names is the URL the store holds, untrimmed and
    # un-defaulted.
    pool = BootstrapPool.resolve({"DATABASE_URL": "sqlite:///somewhere/pool.db"})
    assert pool is not None
    assert pool.database_url == "sqlite:///somewhere/pool.db"


@pytest.mark.parametrize("unset", [None, "", "   "])
def test_resolve_answers_none_when_nothing_names_a_database(unset: str | None) -> None:
    # Absent, empty and whitespace-only all compose no pool — a
    # discoverable state, not an exception: the degrade-don't-break
    # stance every store in this workspace takes.  The operator who
    # means to author the 40-50 worlds is the caller that must not find
    # itself in it, which is the seat's refusal and not this method's.
    env = {} if unset is None else {"DATABASE_URL": unset}
    assert BootstrapPool.resolve(env) is None


def test_a_pool_with_an_unusable_url_is_refused_at_construction() -> None:
    # Construction itself validates the one thing it holds — a
    # non-empty URL — so an empty one never reaches first use to fail
    # mysteriously there.
    with pytest.raises(BootstrapPoolError, match="non-empty database URL"):
        BootstrapPool("   ")


def test_a_url_the_store_cannot_speak_is_refused_by_name() -> None:
    # The spec's single-machine allowance is what a stdlib store can
    # speak; a Postgres URL is refused naming its scheme rather than
    # translated into a file nobody pointed at.  Refused at first use,
    # not at construction — composition must not open a database, so the
    # path (and therefore this refusal) is resolved lazily.
    pool = BootstrapPool("postgres://orchestrator/nullius")
    with pytest.raises(BootstrapPoolError, match="scheme 'postgres'"):
        _ = pool.path


@pytest.mark.parametrize(
    "url",
    ["sqlite:///:memory:", "sqlite://"],
)
def test_an_ephemeral_database_is_refused(url: str) -> None:
    # The one refusal specific to this feature: a pool authored into
    # memory dies with the connection that opened it, so forty-five
    # worlds would be *persisted* and none of them readable —
    # persistence that does not survive its own process is refused
    # outright.
    pool = BootstrapPool(url)
    with pytest.raises(BootstrapPoolError, match="no database path"):
        _ = pool.path


def test_a_host_carrying_url_is_refused() -> None:
    pool = BootstrapPool("sqlite://elsewhere:5432/pool.db")
    with pytest.raises(BootstrapPoolError, match="must not carry a host"):
        _ = pool.path


def test_ensure_schema_is_idempotent(pool: BootstrapPool, database_url: str) -> None:
    # Against a fresh database and one the pool already prepared, the
    # same statement takes the same path — and a second run neither
    # fails nor duplicates anything.
    pool.ensure_schema()
    pool.ensure_schema()
    pool.persist_worlds()
    pool.ensure_schema()
    assert pool.world_count() == 45


# -- The authoring instant --------------------------------------------------------


@pytest.mark.parametrize(
    "naive",
    [
        dt.datetime(2026, 9, 22, 12, 0, 0),  # noqa: DTZ001 - the refusal's subject
        "2026-09-22T12:00:00Z",
        0,
    ],
)
def test_an_instant_that_cannot_name_one_is_refused(
    pool: BootstrapPool, naive: object
) -> None:
    # A naive datetime would place a world's authoring hours away from
    # the process that authored it, in whatever zone the host happens to
    # keep — and nothing in the row would look wrong.  A non-datetime is
    # refused for the plainer reason.
    with pytest.raises(BootstrapPoolError):
        pool.persist_worlds(persisted_at=naive)  # type: ignore[arg-type]


def test_the_stamp_round_trips_through_the_row() -> None:
    # What is written is what reads back: the ISO-8601 UTC stamp and the
    # aware instant are one value in two spellings, and a report
    # ordering by ``created_at`` orders by time.
    instant = dt.datetime(2026, 9, 22, 12, 34, 56, tzinfo=dt.UTC)
    assert parsed_instant("2026-09-22T12:34:56Z") == instant
    with pytest.raises(BootstrapPoolError):
        parsed_instant("not-a-stamp")


def test_the_records_carry_aware_instants(pool: BootstrapPool) -> None:
    # The read side of the stamp: every record's ``created_at`` comes
    # back as an aware UTC datetime, whatever the writer's local zone
    # was.
    pool.persist_worlds()
    for record in pool.worlds():
        assert record.created_at.tzinfo is not None
        assert record.created_at.utcoffset() == dt.timedelta(0)
