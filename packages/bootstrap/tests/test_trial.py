"""Feature 185 — the bootstrap trials' budget bit, persisted false.

app_spec.xml, "Bootstrap Worlds", feature 185: *System charges no
statistical budget for a bootstrap world, persisting charges_budget as
false on those trials.*  This suite holds the member to the sentence the
way its sibling suites hold theirs — clause by clause, from the
documented side:

* **"charges no statistical budget"** — the budget the question reports
  is the whole budget before and after every recorded trial (a counter
  anywhere would be a budget, and the budget is the trial's fact, not
  the world's), and the published directive
  :data:`~bootstrap.TRIAL_CHARGES_BUDGET` is ``False`` — not a default,
  the only value the store can write.
* **"persisting charges_budget as false"** — every row the ledger writes
  reads back with ``charges_budget`` ``False``, the SQLite column holds
  the ``0`` of that bit, and the persistence is a fact about the *store*
  rather than a convention of its writers: the table's own CHECK refuses
  a charging trial a hand tried to seat, and the record value refuses a
  hand-built one before the store is ever touched.  The downstream stake
  is feature 93's — ``K_effective`` counts only ``charges_budget`` true
  rows, so the count this ledger's rows can inflate is exactly zero.
* **"on those trials"** — the trials are the question's probes (feature
  184, the seam this feature depends on): one row per newly revealed
  cell, attributed from the observation's own payload rather than
  restated by the caller, a re-probe records nothing new, two replays
  each record their own, and the authored world, the ported world
  (feature 190) and the composed world record through one duck-typed
  code path.

Beside the clause-by-clause claims sit the store's own guards — the
object that is not a question, the payload a row cannot be attributed
from, the naive stamp, the reads' world filter — each pinned by the
error it raises and the subject it names, the discipline every store
suite in this workspace follows.
"""

from __future__ import annotations

import datetime as dt
import sqlite3
from types import SimpleNamespace
from typing import Any

import pytest
from bootstrap import (
    DEFAULT_PORTED_WORLD_ID,
    HYPERPARAMETER_WORLD_ID,
    TRIAL_CHARGES_BUDGET,
    TRIAL_TABLE,
    BootstrapPool,
    BootstrapPoolError,
    BootstrapTrialLedger,
    BootstrapWorldError,
    HyperparameterWorld,
    Provenance,
    TrialRecord,
    ported_question_for,
    ported_world,
    question_for,
    world_census,
)


@pytest.fixture
def ledger(database_url: str) -> BootstrapTrialLedger:
    """Feature 185's trial ledger, pointed at this test's own database.

    Built beside the pool's fixture over the same URL, because the two
    stores share one deployment fact (``DATABASE_URL``): the worlds and
    the trials of a deployment live in one database, which is what makes
    *"persisting charges_budget as false on those trials"* a statement
    about the accounting the system reads rather than about a side file.
    """
    return BootstrapTrialLedger(database_url)


@pytest.fixture
def stamp() -> dt.datetime:
    """An aware instant a test can name, so rows carry a stated time."""
    return dt.datetime(2026, 9, 22, 12, 0, 0, tzinfo=dt.UTC)


def _raw_rows(ledger: BootstrapTrialLedger) -> list[tuple]:
    """The trial table's raw rows, read past the store's own read path.

    The store's ``trials()`` coerces the stored bit to the ``bool`` the
    record holds; the claims about *persistence* need the spelling the
    column actually keeps, so they read it directly — the same
    store-bypassing read the pool suite and the census suite make of
    their tables.
    """
    with sqlite3.connect(ledger.path) as connection:
        return connection.execute(
            f"SELECT seq, ts, world_id, node_id, charges_budget "
            f"FROM {TRIAL_TABLE} ORDER BY seq"
        ).fetchall()


# -- "charges no statistical budget" ---------------------------------------------


def test_the_published_directive_is_false() -> None:
    # §10.6 publishes that a bootstrap world's probes are free, and the
    # member publishes the directive as a value: False, a genuine bool,
    # and the only value the store's table can hold. A caller reads the
    # constant rather than restating the fact.
    assert TRIAL_CHARGES_BUDGET is False


def test_recording_never_touches_the_budget_the_question_reports(
    ledger: BootstrapTrialLedger, world: HyperparameterWorld
) -> None:
    # The budget is the question's report, and the report is the whole
    # budget, always. Recording a trial cannot decrement it — a counter
    # would be a budget, and the budget is the trial's fact, recorded on
    # the row, not kept by the world or the question.
    question = question_for(world)
    assert question.budget_remaining() == float("inf")
    ledger.record_trials(question, [world.canonical_node()])
    assert question.budget_remaining() == float("inf")


# -- "persisting charges_budget as false" ----------------------------------------


def test_every_recorded_trial_persists_charges_budget_false(
    ledger: BootstrapTrialLedger, world: HyperparameterWorld
) -> None:
    # The sentence's second clause, read back: every trial the ledger
    # records carries the directive False — `is False`, not merely
    # falsy, because the bit §8's column carries is a bool and the read
    # must answer it as one.
    question = question_for(world)
    cells = [world.canonical_node(), "d+1.i+0.s+0.a+0", "d+2.i+0.s+0.a+0"]
    recorded = ledger.record_trials(question, cells)
    assert len(recorded) == 3
    for trial in recorded:
        assert trial.charges_budget is False
    for trial in ledger.trials():
        assert trial.charges_budget is False


def test_the_stored_bit_is_zero(
    ledger: BootstrapTrialLedger, world: HyperparameterWorld
) -> None:
    # The SQLite spelling of the directive: a BOOLEAN column stores the
    # integer 0, and that is what the write puts there — the literal 0 of
    # the INSERT statement, never a parameter the caller could spell.
    ledger.record_trials(question_for(world), [world.canonical_node()])
    rows = _raw_rows(ledger)
    assert [row[4] for row in rows] == [0]


def test_no_row_this_ledger_holds_can_inflate_k_effective(
    ledger: BootstrapTrialLedger, world: HyperparameterWorld
) -> None:
    # Feature 93 counts K_effective over the rows where charges_budget is
    # true, "so null nodes never inflate the trial count". The bootstrap
    # half must not either, and here is that fact measured: after trials
    # are recorded, the count of budget-charging rows the table could
    # hand any counter is exactly zero.
    ledger.record_trials(
        question_for(world), [world.canonical_node(), "d+1.i+0.s+0.a+0"]
    )
    with sqlite3.connect(ledger.path) as connection:
        (charged,) = connection.execute(
            f"SELECT COUNT(*) FROM {TRIAL_TABLE} WHERE charges_budget"
        ).fetchone()
    assert charged == 0


def test_the_table_refuses_a_charging_trial_by_hand(
    ledger: BootstrapTrialLedger, world: HyperparameterWorld
) -> None:
    # The persistence is enforced by the store, not by convention of its
    # writers: the table's own CHECK (charges_budget = 0) refuses a row a
    # hand tried to seat with the bit set — the append-only tables'
    # "a hand that reached past the writer" hazard, met at the table.
    ledger.record_trials(question_for(world), [world.canonical_node()])
    with (
        pytest.raises(sqlite3.IntegrityError),
        sqlite3.connect(ledger.path) as connection,
        connection,
    ):
        connection.execute(
            f"INSERT INTO {TRIAL_TABLE} (ts, world_id, node_id, charges_budget) "
            f"VALUES ('2026-09-22T00:00:00Z', 'w', 'n', 1)"
        )
    # The refused row is not in the log.
    assert ledger.trial_count() == 1


def test_a_hand_built_record_cannot_say_a_trial_charged(stamp: dt.datetime) -> None:
    # The CHECK's twin at the value layer: a record of a bootstrap trial
    # that said it charged budget describes no row the table can hold,
    # and it is refused by name before any store is touched — in both
    # spellings a hand might reach for, the bool and the stored int.
    for wrong in (True, 1):
        with pytest.raises(BootstrapPoolError, match="charges no statistical budget"):
            TrialRecord(
                seq=1,
                ts=stamp,
                world_id=HYPERPARAMETER_WORLD_ID,
                node_id="d+1.i+0.s+0.a+0",
                charges_budget=wrong,
            )


def test_a_record_round_trips_with_the_bit_intact(
    ledger: BootstrapTrialLedger, world: HyperparameterWorld, stamp: dt.datetime
) -> None:
    # A record built with the published directive is the record the log
    # holds, and it round-trips through the store's row() shape with the
    # bit in its stored spelling — 0, always, because that is the only
    # value the record can hold.
    ledger.record_trials(
        question_for(world), [world.canonical_node()], recorded_at=stamp
    )
    (trial,) = ledger.trials()
    assert trial == TrialRecord(
        seq=trial.seq,
        ts=stamp,
        world_id=HYPERPARAMETER_WORLD_ID,
        node_id=world.canonical_node(),
        charges_budget=TRIAL_CHARGES_BUDGET,
    )
    row = trial.row()
    assert row["charges_budget"] == 0
    assert row["ts"] == "2026-09-22T12:00:00Z"


# -- "on those trials": the question's seam --------------------------------------


def test_record_trials_reveals_through_the_question(
    ledger: BootstrapTrialLedger, world: HyperparameterWorld
) -> None:
    # The trial *is* the probe: one call reveals the batch through the
    # question's own probe_batch and records exactly what it revealed —
    # one row per newly revealed cell, in probe order, with the log's
    # seqs ascending from 1. The record and the reveal cannot drift
    # apart, because the rows are built from the probe's own return.
    question = question_for(world)
    cells = ["d+1.i+0.s+0.a+0", "d+0.i+1.s+0.a+0"]
    recorded = ledger.record_trials(question, cells)
    assert sorted(trial.node_id for trial in recorded) == sorted(cells)
    assert set(question.observed()) == set(cells)
    assert [trial.seq for trial in recorded] == [1, 2]


def test_the_row_is_attributed_from_the_payload(
    ledger: BootstrapTrialLedger, world: HyperparameterWorld
) -> None:
    # The row's world is the observation's own world_id — the attribution
    # the payload carries for §10.6's "report the two pools separately" —
    # not a value the caller restated: the caller never names a world to
    # record_trials at all, and the row still lands on the right one.
    question = question_for(world)
    (trial,) = ledger.record_trials(question, [world.canonical_node()])
    observation = question.observed()[world.canonical_node()]
    assert trial.world_id == observation.world_id == world.world_id
    assert trial.node_id == observation.node_id


def test_a_reprobe_records_nothing_new(
    ledger: BootstrapTrialLedger, world: HyperparameterWorld
) -> None:
    # The question is idempotent on its revealed set, and so is the log:
    # a re-probe of cells the question already holds records nothing and
    # answers () — the trial already has its row, and an append-only log
    # is not re-appendable.
    question = question_for(world)
    cell = world.canonical_node()
    assert len(ledger.record_trials(question, [cell])) == 1
    assert ledger.record_trials(question, [cell]) == ()
    assert ledger.trial_count() == 1


def test_two_replays_each_record_their_own_trials(
    ledger: BootstrapTrialLedger, world: HyperparameterWorld
) -> None:
    # Each policy's evaluation is its own trial: two questions over one
    # world, probing the same cell, record two rows — both free, which is
    # the point of the world the rows are recorded against.
    first, second = question_for(world), question_for(world)
    cell = world.canonical_node()
    ledger.record_trials(first, [cell])
    ledger.record_trials(second, [cell])
    trials = ledger.trials()
    assert len(trials) == 2
    assert {trial.node_id for trial in trials} == {cell}
    assert all(trial.charges_budget is False for trial in trials)


def test_a_ported_worlds_trials_are_recorded_the_same(ledger: BootstrapTrialLedger) -> None:
    # Feature 190's adapter fronts the identical question interface, so
    # the recorder — duck-typed on the seam, not on a class — records a
    # ported world's trials through the same one code path, attributed to
    # the ported world's own id.
    world = ported_world(
        label_fn=lambda node: 0.5,
        provenance=Provenance(
            source_commit="71a513b" + "0" * 33,
            dataset_manifest="0" * 64,
        ),
    )
    question = ported_question_for(world)
    (trial,) = ledger.record_trials(question, [question.legal_roots()[0]])
    assert trial.world_id == DEFAULT_PORTED_WORLD_ID
    assert trial.charges_budget is False


def test_the_composed_world_records_through_the_seam(ledger: BootstrapTrialLedger) -> None:
    # The module loader imports this member under a synthetic name and
    # re-executes it, so the world create_app() hands out is a second
    # class object. The recorder rides feature 184's duck-typed seam, so
    # the composed world records through it exactly as the direct one
    # does — "one policy, both pools", held at the composition seam.
    from app.module_loader import create_app

    world = create_app().get("bootstrap")
    assert world is not None and type(world).__name__ == "HyperparameterWorld"
    (trial,) = ledger.record_trials(question_for(world), [world.canonical_node()])
    assert trial.world_id == HYPERPARAMETER_WORLD_ID
    assert trial.charges_budget is False


def test_a_refused_batch_records_nothing(
    ledger: BootstrapTrialLedger, world: HyperparameterWorld
) -> None:
    # A batch that names a cell the world does not hold is the question's
    # own refusal (BootstrapWorldError, untranslated — the caller's
    # except already speaks it), and because the write runs only after
    # the probe answered, a refused batch records nothing at all.
    question = question_for(world)
    with pytest.raises(BootstrapWorldError):
        ledger.record_trials(question, [world.canonical_node(), "d+9.i+0.s+0.a+0"])
    assert ledger.trial_count() == 0
    # And the good cell of the refused batch was not half-applied.
    assert question.observed() == {}


# -- the log's reads --------------------------------------------------------------


def test_the_log_ascends_and_counts(
    ledger: BootstrapTrialLedger,
    world: HyperparameterWorld,
    other_world: HyperparameterWorld,
) -> None:
    # The log's own order is the order it was appended in: seqs strictly
    # ascending across batches, trial_count answering without building
    # every record, and the world filter splitting the log the way §10.6
    # splits the pools — by the world the row itself carries.
    first, second = question_for(world), question_for(other_world)
    ledger.record_trials(first, [world.canonical_node(), "d+1.i+0.s+0.a+0"])
    ledger.record_trials(second, [other_world.canonical_node()])
    trials = ledger.trials()
    assert [trial.seq for trial in trials] == [1, 2, 3]
    assert ledger.trial_count() == 3
    assert ledger.trial_count(world.world_id) == 2
    assert ledger.trial_count(other_world.world_id) == 1
    assert {trial.world_id for trial in ledger.trials(world.world_id)} == {
        world.world_id
    }


def test_an_empty_log_reads_empty(ledger: BootstrapTrialLedger) -> None:
    # An empty log is a statement about what has been probed, not about
    # the deployment — it reads as exactly no trials, and the schema work
    # the read performs is idempotent, so asking is always safe.
    assert ledger.trials() == ()
    assert ledger.trial_count() == 0
    assert ledger.trials("any-world") == ()


def test_an_empty_batch_records_nothing(
    ledger: BootstrapTrialLedger, world: HyperparameterWorld
) -> None:
    # A probe of no cells reveals nothing, and a record of no probes
    # writes nothing — the question's own empty-batch answer, carried.
    assert ledger.record_trials(question_for(world), []) == ()
    assert ledger.trial_count() == 0


def test_the_reads_refuse_a_blank_world_id(
    ledger: BootstrapTrialLedger, world: HyperparameterWorld
) -> None:
    # A filter that addressed no world would silently answer the whole
    # log as one world's trials, so the reads refuse a blank id by name —
    # the same guard the pool's own reads state.
    ledger.record_trials(question_for(world), [world.canonical_node()])
    for blank in ("", "   "):
        with pytest.raises(BootstrapPoolError, match="non-empty string"):
            ledger.trials(blank)
        with pytest.raises(BootstrapPoolError, match="non-empty string"):
            ledger.trial_count(blank)


# -- the store's guards ------------------------------------------------------------


def test_a_non_question_is_refused_before_the_disk(ledger: BootstrapTrialLedger) -> None:
    # Trials are recorded through the question interface a policy is
    # handed; an object that cannot probe names no trial this ledger
    # could record, and the refusal lands before anything touches the
    # disk — a validation that ran after the schema work would be a
    # validation that ran too late to be one.
    for not_a_question in ("bootstrap", 185, SimpleNamespace(probe_batch="no")):
        with pytest.raises(BootstrapPoolError, match="probe_batch"):
            ledger.record_trials(
                not_a_question,  # type: ignore[arg-type]
                ["d+1.i+0.s+0.a+0"],
            )
    assert not ledger.path.exists()


def test_a_payload_that_cannot_be_attributed_is_refused(
    ledger: BootstrapTrialLedger,
) -> None:
    # The rows are built from the payload the probe returned, so a
    # payload that cannot attribute a row — no world on the observation,
    # no node, or not a mapping at all — records nothing rather than half
    # a batch: validated in full before the transaction opens.
    class _StubQuestion:
        def __init__(self, payload: Any) -> None:
            self._payload = payload

        def probe_batch(self, cells: Any, on_reveal: Any = None) -> Any:
            return self._payload

    cell = "d+1.i+0.s+0.a+0"
    with pytest.raises(BootstrapPoolError, match="world it was earned on"):
        ledger.record_trials(
            _StubQuestion({cell: SimpleNamespace(node_id=cell)}), [cell]
        )
    with pytest.raises(BootstrapPoolError, match="node it labels"):
        ledger.record_trials(
            _StubQuestion({cell: SimpleNamespace(world_id="bootstrap-hpo-x")}), [cell]
        )
    with pytest.raises(BootstrapPoolError, match="not a mapping"):
        ledger.record_trials(_StubQuestion([cell]), [cell])
    assert ledger.trial_count() == 0


@pytest.mark.parametrize(
    "naive",
    [
        dt.datetime(2026, 9, 22, 12, 0, 0),  # noqa: DTZ001 - the refusal's subject
        "2026-09-22T12:00:00Z",
        0,
    ],
)
def test_a_recorded_at_that_cannot_name_an_instant_is_refused(
    ledger: BootstrapTrialLedger, world: HyperparameterWorld, naive: object
) -> None:
    # The stamp is part of the log's history; a naive one would place the
    # trial hours away from the process that ran it, in whatever zone the
    # host happens to keep — and nothing in the row would look wrong.  A
    # non-datetime is refused for the plainer reason.  Both land before
    # any row is written, through the same aware-instant validation the
    # pool's authoring stamp takes.
    with pytest.raises(BootstrapPoolError):
        ledger.record_trials(
            question_for(world),
            [world.canonical_node()],
            recorded_at=naive,  # type: ignore[arg-type]
        )
    assert ledger.trial_count() == 0


# -- one deployment, one database, two stores --------------------------------------


def test_resolve_reads_the_same_variable_the_pool_reads(database_url: str) -> None:
    # The ledger resolves DATABASE_URL exactly as the pool resolves it:
    # the same variable, read the same way, so a deployment's worlds and
    # its trials can never come to live in two different databases — and
    # absent is a discoverable None, not an error, the pool's own stance.
    resolved = BootstrapTrialLedger.resolve({"DATABASE_URL": database_url})
    assert resolved is not None
    assert resolved.database_url == database_url
    assert BootstrapTrialLedger.resolve({}) is None
    assert BootstrapTrialLedger.resolve({"DATABASE_URL": "   "}) is None


def test_persistence_survives_a_second_ledger(
    database_url: str, world: HyperparameterWorld
) -> None:
    # Persistence that did not survive its own process is the one state
    # the pool refuses outright, and the log takes the same terms: a
    # second ledger over the same URL reads the same rows, seqs and all.
    first = BootstrapTrialLedger(database_url)
    first.record_trials(question_for(world), [world.canonical_node()])
    second = BootstrapTrialLedger(database_url)
    assert second.trials() == first.trials()
    assert second.trial_count() == 1
    # And the schema work is idempotent — asking again changes nothing.
    second.ensure_schema()
    assert second.trial_count() == 1


def test_the_store_shares_the_pools_database(
    pool: BootstrapPool, world: HyperparameterWorld
) -> None:
    # bootstrap_trial and bootstrap_world are two tables of one
    # deployment fact: recording trials beside a seated pool changes
    # neither the pool's count nor the census's two figures, because the
    # trials are rows of a log the worlds are not rows of — and no
    # bootstrap trial, recorded or not, ever pads what the financial
    # half of anything reads.  The replay pool is seeded with one
    # financial world so the claim is measured against a nonzero figure
    # rather than two zeros.
    pool.ensure_schema()
    ledger = BootstrapTrialLedger(pool.database_url)
    with sqlite3.connect(pool.path) as connection, connection:
        connection.execute(
            "CREATE TABLE IF NOT EXISTS replay_score ("
            "id TEXT PRIMARY KEY, policy_version TEXT NOT NULL, "
            "world_id TEXT NOT NULL, beta REAL NOT NULL, score REAL NOT NULL, "
            "committed_pick TEXT, is_holdout BOOLEAN NOT NULL DEFAULT 0, "
            "created_at TEXT NOT NULL)"
        )
        connection.execute(
            "INSERT INTO replay_score (id, policy_version, world_id, beta, "
            "score, committed_pick, is_holdout, created_at) "
            "VALUES ('r1', 'p1', '11111111-1111-1111-1111-111111111111', "
            "1.0, 0.1, NULL, 0, '2026-09-22T00:00:00Z')"
        )
    before = world_census(pool)
    assert before.n_financial == 1 and before.n_bootstrap == 0

    ledger.record_trials(question_for(world), [world.canonical_node()])
    ledger.record_trials(question_for(world), ["d+1.i+0.s+0.a+0"])

    assert world_census(pool) == before  # neither figure moved
    assert pool.world_count() == 0  # a trial is not a world
    assert ledger.trial_count() == 2  # and the trials are all still there
