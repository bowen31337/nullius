"""Feature 123's store half: the p-value persisted against its campaign.

app_spec.xml, "Null Oracle & Planted Nulls", feature 123: *System persists
the p-value of a two-sample Kolmogorov-Smirnov test comparing in-sample
scores of null nodes against real nodes per campaign.*  ``test_ks.py`` pins
the test; this suite pins the writing down.

What is asserted here is mostly not *that a number was stored* — that is one
test — but the properties that make the stored number trustworthy, because
§7.4's p-value is what feature 124 voids a campaign on, halts dreaming over
and excludes it from the replay pool:

* **it lands where the system reads it.**  ``campaign.ks_pvalue``, the column
  ``migrations/versions/0111_campaign_table.py`` created for exactly this
  feature, filled by the guard and not by the orchestrator.  The store's
  restatement of that table's DDL is asserted column-for-column against the
  migration's own ``statements("sqlite")``, because a store and a migration
  that drift apart on ``campaign`` are two schemas wearing one name — and
  because that is the agreement ``nulloracle.ksguard``'s module docstring
  claims for itself.
* **the verdict is not written.**  §7.4's ``p < 0.05`` comparison and the
  ``VOID`` verdict belong to feature 124; the guard *measures*.  So a
  campaign whose p-value would void it is asserted to come out of the guard
  with its ``calibration_status`` still ``'ok'``.
* **the two halves are one reading.**  The number on the campaign row and the
  provenance beside it are written in one transaction and refused in either
  half, so a store can never hand back a p-value whose statistic and sample
  sizes are missing or wrong.
* **a reading is about a campaign.**  A campaign the table does not hold is
  refused by name rather than created, and a sample the test refuses leaves
  no row claiming the guard ran.
* **nothing but counts crosses the barrier.**  §4.2's rule, asserted on what
  the table actually holds rather than only on the value handed back: no
  score, no node id, in any column.
"""

from __future__ import annotations

import importlib.util
import sqlite3
import uuid
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from nulloracle import (
    CAMPAIGN_TABLE,
    DATABASE_URL_ENV,
    KS_ASYMPTOTIC,
    KS_EXACT,
    KS_GUARD_TABLE,
    KsGuard,
    KsGuardError,
    KsGuardRecord,
    KsTestError,
    guard_record_from_row,
    ks_two_sample,
    load_ks_guard,
    persist_ks_pvalue,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
MIGRATION_PATH = REPO_ROOT / "migrations" / "versions" / "0111_campaign_table.py"

#: A campaign's planning-time row: the three ``NOT NULL`` columns with no
#: default, in the shape ``migrations/versions/0111_campaign_table.py``
#: describes (Type-R at W = 12, so φ = clip(2/12, 0.15, 0.35) = 0.1667…).
CAMPAIGN_COLUMNS = ("campaign_type", "workspace_count", "null_fraction")
CAMPAIGN_VALUES = ("Type-R", 12, 0.1667)


# -- Helpers ---------------------------------------------------------------------


def _store(tmp_path: Path, name: str = "ksguard.db") -> tuple[KsGuard, str]:
    """A guard over a fresh SQLite file, with its ``DATABASE_URL`` spelling."""
    path = tmp_path / name
    url = f"sqlite:///{path}"
    return KsGuard(url), url


def _nodes(count: int) -> list[str]:
    return [str(uuid.uuid4()) for _ in range(count)]


def _separated(count: int) -> tuple[dict[str, float], dict[str, float], dict[str, float]]:
    """Samples that are plainly separable, plus a real-side sample.

    Returns ``(null, real, flat)``: ``flat`` is a real-side sample drawn from
    the null side's own values, so a test wanting a *large* p-value has one
    without a second clock or a second seed.
    """
    nodes = _nodes(count * 2)
    null = {node: index * 0.01 for index, node in enumerate(nodes[:count])}
    real = {node: index * 0.01 + 50.0 for index, node in enumerate(nodes[count:])}
    return null, real, dict(real)


def _campaign(guard: KsGuard, campaign_id: str | None = None, **overrides) -> str:
    """Insert a campaign row the way its planner would, and return its id."""
    identifier = campaign_id or str(uuid.uuid4())
    values = dict(zip(CAMPAIGN_COLUMNS, CAMPAIGN_VALUES))
    values.update(overrides)
    with closing(guard._connect()) as connection, connection:
        connection.execute(
            f"INSERT INTO {CAMPAIGN_TABLE} (id, {', '.join(values)}) "
                f"VALUES (?, {', '.join('?' * len(values))})",
            (identifier, *values.values()),
        )
    return identifier


def _row(guard: KsGuard, campaign_id: str) -> tuple:
    """The campaign row's ``(ks_pvalue, calibration_status)``, read raw."""
    with closing(guard._connect()) as connection:
        cursor = connection.execute(
            f"SELECT ks_pvalue, calibration_status FROM {CAMPAIGN_TABLE} "
            "WHERE id = ?",
            (campaign_id,),
        )
        try:
            return cursor.fetchone()
        finally:
            cursor.close()


def _guard_rows(guard: KsGuard) -> list[tuple]:
    with closing(guard._connect()) as connection:
        cursor = connection.execute(f"SELECT * FROM {KS_GUARD_TABLE}")
        try:
            return cursor.fetchall()
        finally:
            cursor.close()


def _columns(guard: KsGuard, table: str) -> list[tuple]:
    """``PRAGMA table_info`` for ``table``, as ``(name, type, notnull, dflt, pk)``."""
    with closing(guard._connect()) as connection:
        cursor = connection.execute(f"PRAGMA table_info({table})")
        try:
            return [
                (row[1], row[2], row[3], row[4], row[5])
                for row in cursor.fetchall()
            ]
        finally:
            cursor.close()


def _migration():
    """``migrations/versions/0111_campaign_table.py``, loaded by path.

    By path rather than by import because that is how a migration runner
    loads it: the file is not a module on any package's ``sys.path``, and a
    test that could only reach it through an import would be testing a
    different arrangement from the one that runs.
    """
    spec = importlib.util.spec_from_file_location(
        "migration_0111_campaign_table", MIGRATION_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(autouse=True)
def _database_url_isolation(monkeypatch: pytest.MonkeyPatch) -> None:
    """Start every test with no ``DATABASE_URL`` in the environment.

    Autouse and unconditional, mirroring the member's other isolation
    fixtures: the default state of a test is a deployment that names no
    relational store, and the tests that assert on the *unconfigured*
    behaviour then do not fight a fixture that helpfully configured one. Each
    test that wants a store builds its own over ``tmp_path``, so no test in
    this suite can reach a real database — the same guarantee the conftest
    states for the sidecar's path.
    """
    monkeypatch.delenv(DATABASE_URL_ENV, raising=False)


# -- The write -------------------------------------------------------------------


class TestThePValueLandsOnTheCampaign:
    def test_a_guarded_campaign_carries_the_number_the_test_computed(
        self, tmp_path: Path
    ) -> None:
        guard, _ = _store(tmp_path)
        campaign = _campaign(guard)
        null, real, _ = _separated(40)
        measured = ks_two_sample(null, real)
        record = guard.guard(campaign, null, real)
        assert record.pvalue == measured.pvalue
        assert record.statistic == measured.statistic
        assert record.null_count == 40
        assert record.real_count == 40
        assert record.method == measured.method
        stored, status = _row(guard, campaign)
        assert stored == measured.pvalue
        assert status == "ok"

    def test_the_campaign_row_is_the_one_the_system_reads_it_from(
        self, tmp_path: Path
    ) -> None:
        # The spec's own location: ``campaign.ks_pvalue``, the column
        # ``0111`` created for this feature and *not* a column of the store's
        # own table. Feature 124's verdict, the dashboard's instrument status
        # and anything else wanting the number look for it there, so a store
        # that kept it only in its own table would be a second answer.
        guard, _ = _store(tmp_path)
        campaign = _campaign(guard)
        null, real, _ = _separated(20)
        record = guard.guard(campaign, null, real)
        anon = KsGuard(f"sqlite:///{guard.path}")
        with closing(anon._connect()) as connection:
            cursor = connection.execute(
                f"SELECT ks_pvalue FROM {CAMPAIGN_TABLE} WHERE id = ?",
                (campaign,),
            )
            try:
                assert cursor.fetchone()[0] == record.pvalue
            finally:
                cursor.close()

    def test_the_provenance_beside_the_number_is_what_the_loader_returns(
        self, tmp_path: Path
    ) -> None:
        # The guard row is what makes a stored ``0.31`` interpretable: it is
        # 0.31 *from 40 nodes, by the exact estimator*, not 0.31 from four.
        guard, _ = _store(tmp_path)
        campaign = _campaign(guard)
        null, real, _ = _separated(30)
        written = guard.guard(campaign, null, real)
        loaded = guard.load(campaign)
        assert loaded == written
        assert loaded is not None
        assert loaded.measurement == ks_two_sample(null, real)
        assert loaded.to_payload() == written.to_payload()

    def test_the_reading_is_stamped_with_when_the_guard_ran(
        self, tmp_path: Path
    ) -> None:
        guard, _ = _store(tmp_path)
        campaign = _campaign(guard)
        null, real, _ = _separated(10)
        record = guard.guard(campaign, null, real)
        assert record.seen_at.tzinfo is not None
        assert record.seen_at.utcoffset() == timedelta(0)
        assert record.seen_at.microsecond == 0
        assert abs((datetime.now(timezone.utc) - record.seen_at).total_seconds()) < 60

    def test_a_replayed_guard_stamps_the_instant_the_original_did(
        self, tmp_path: Path
    ) -> None:
        # §12's determinism contract reaches the write path: a replayed guard
        # run must produce the row the original produced, which means the
        # caller supplies the instant rather than the store minting a new one.
        guard, _ = _store(tmp_path)
        campaign = _campaign(guard)
        null, real, _ = _separated(10)
        instant = datetime(2026, 3, 1, 12, 30, 45, tzinfo=timezone.utc)
        record = guard.guard(campaign, null, real, seen_at=instant)
        assert record.seen_at == instant
        assert guard.load(campaign).to_payload()["seen_at"] == instant.isoformat()

    def test_the_guard_never_writes_the_verdict(self, tmp_path: Path) -> None:
        # §7.4 spells the consequence — ``p < 0.05`` → ``VOID`` — and
        # app_spec.xml gives that comparison to feature 124. This feature
        # *measures*. A guard that also decided would be a threshold nobody
        # could audit without changing what a measurement means, so a
        # campaign whose p-value is decisively detectable comes out of the
        # guard still calibrated.
        guard, _ = _store(tmp_path)
        campaign = _campaign(guard)
        record = guard.guard(
            campaign, [1.0, 2.0, 3.0, 4.0], [5.0, 6.0, 7.0, 8.0]
        )
        assert record.pvalue < 0.05, "this case must be one 124 would void on"
        assert _row(guard, campaign) == (record.pvalue, "ok")

    def test_the_write_is_idempotent_by_campaign(self, tmp_path: Path) -> None:
        # §7.4's own instruction is "investigate the block length and
        # permutation scheme before proceeding", so a campaign is expected to
        # be guarded more than once. The grain is the campaign: a re-read
        # refreshes the reading rather than appending a second one, and what
        # the table holds is the latest reading and nothing else.
        guard, _ = _store(tmp_path)
        campaign = _campaign(guard)
        first_null, first_real, _ = _separated(20)
        second_null, second_real, _ = _separated(25)
        first = guard.guard(campaign, first_null, first_real)
        second = guard.guard(campaign, second_null, second_real)
        assert first.pvalue != second.pvalue
        rows = _guard_rows(guard)
        assert len(rows) == 1
        assert guard.load(campaign) == second
        assert _row(guard, campaign)[0] == second.pvalue

    def test_a_re_guard_of_the_same_samples_changes_nothing(
        self, tmp_path: Path
    ) -> None:
        guard, _ = _store(tmp_path)
        campaign = _campaign(guard)
        null, real, _ = _separated(15)
        instant = datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
        first = guard.guard(campaign, null, real, seen_at=instant)
        again = guard.guard(campaign, null, real, seen_at=instant)
        assert first == again
        assert len(_guard_rows(guard)) == 1

    def test_the_campaigns_own_columns_are_untouched(self, tmp_path: Path) -> None:
        # The guard fills one column of a row that is not its own. The
        # planning-time facts — the type, W, φ — are the planner's, and a
        # guard run that rewrote any of them would be quietly redefining the
        # campaign it just measured.
        guard, _ = _store(tmp_path)
        campaign = _campaign(guard)
        null, real, _ = _separated(10)
        guard.guard(campaign, null, real)
        with closing(guard._connect()) as connection:
            cursor = connection.execute(
                f"SELECT campaign_type, workspace_count, null_fraction, "
                f"created_at FROM {CAMPAIGN_TABLE} WHERE id = ?",
                (campaign,),
            )
            try:
                row = cursor.fetchone()
            finally:
                cursor.close()
        assert row[0:3] == CAMPAIGN_VALUES
        assert row[3] is not None

    def test_the_guard_table_gains_a_column_for_nothing_but_its_own_reading(
        self, tmp_path: Path
    ) -> None:
        # The store's own table is this feature's provenance and nothing
        # else: one row per campaign, seven columns, no node and no score.
        guard, _ = _store(tmp_path)
        names = [column[0] for column in _columns(guard, KS_GUARD_TABLE)]
        assert names == [
            "campaign_id",
            "pvalue",
            "statistic",
            "null_count",
            "real_count",
            "method",
            "seen_at",
        ]


class TestTheGuardRefusesRatherThanGuesses:
    def test_a_campaign_the_table_does_not_hold_is_refused_by_name(
        self, tmp_path: Path
    ) -> None:
        # The p-value is a fact *about a campaign*. A guard that wrote
        # ``ks_pvalue`` onto a row it created would be inventing the campaign
        # the number belongs to — and the fraction the whole blinding
        # discipline is built around is fixed by the planner, not here.
        guard, _ = _store(tmp_path)
        unplanned = str(uuid.uuid4())
        null, real, _ = _separated(10)
        with pytest.raises(KsGuardError, match="holds no row") as raised:
            guard.guard(unplanned, null, real)
        assert "per campaign" in str(raised.value)
        assert _guard_rows(guard) == []

    def test_a_malformed_campaign_id_is_a_store_error_not_a_sidecar_one(
        self, tmp_path: Path
    ) -> None:
        # The taxonomy's distinction: a malformed id handed to the *guard* is
        # a store-contract failure. A caller reading ``SidecarError`` out of a
        # KS guard would look in the wrong module for the cause.
        from nulloracle import SidecarError

        guard, _ = _store(tmp_path)
        null, real, _ = _separated(10)
        with pytest.raises(KsGuardError, match="is not a UUID") as raised:
            guard.guard("not-a-uuid", null, real)
        assert not isinstance(raised.value, SidecarError)
        assert isinstance(raised.value.__cause__, SidecarError)

    def test_a_refused_sample_leaves_no_row_claiming_the_guard_ran(
        self, tmp_path: Path
    ) -> None:
        # Ordering, asserted on the disk: the measurement runs *before* the
        # store is opened at all, so a sample the test refuses cannot leave a
        # half — or even a database file — behind. A guard that opened first
        # and measured second would have to unwind a write to get here.
        guard, _ = _store(tmp_path)
        campaign = _campaign(guard)
        path = guard.path
        path.unlink()
        before = guard.load(campaign)
        assert before is None
        path.unlink()
        with pytest.raises(KsTestError, match="non-finite"):
            guard.guard(campaign, [1.0, float("nan")], [3.0, 4.0])
        assert not path.exists()

    def test_a_shared_node_is_refused_before_the_campaign_is_touched(
        self, tmp_path: Path
    ) -> None:
        # Two samples disagreeing about a node's null status are not the two
        # populations §7.4 compares, and the campaign must come out of the
        # refusal exactly as it went in.
        guard, _ = _store(tmp_path)
        campaign = _campaign(guard)
        nodes = _nodes(4)
        sample = {nodes[0]: 1.0, nodes[1]: 2.0, nodes[2]: 3.0}
        with pytest.raises(KsTestError, match="named as both null and real"):
            guard.guard(campaign, sample, {**sample, nodes[3]: 9.0})
        assert _row(guard, campaign) == (None, "ok")
        assert _guard_rows(guard) == []

    def test_the_store_refuses_a_url_it_cannot_speak(self, tmp_path: Path) -> None:
        # Composition must not raise — a deployment whose DATABASE_URL points
        # at Postgres still composes, and the store that cannot speak its URL
        # says so the first time it is *used*. The alternative is an app that
        # will not start because one member's driver is missing.
        guard = KsGuard("postgresql://db.internal/nullius")
        assert guard.database_url == "postgresql://db.internal/nullius"
        with pytest.raises(KsGuardError, match="unsupported"):
            guard.load(str(uuid.uuid4()))

    def test_a_host_carrying_sqlite_url_is_refused(self, tmp_path: Path) -> None:
        with pytest.raises(KsGuardError, match="must not carry a host"):
            KsGuard("sqlite://elsewhere/nullius.db").path

    def test_an_in_memory_url_is_refused(self, tmp_path: Path) -> None:
        # An in-memory database dies with the connection that opened it, and a
        # guard reading that vanished would leave a campaign looking un-read
        # when it had in fact been read and voided. ``sqlite://`` and
        # ``sqlite:///:memory:`` are the two spellings of that; the pathless
        # ``sqlite://localhost`` is the third (its "host" is a relative file
        # name with no path, so the store's host rule catches it first — see
        # the next test). ``sqlite:///localhost`` is deliberately **not** here:
        # it names a relative file called ``localhost``, which is a real
        # database path.
        for url in ("sqlite://", "sqlite:///:memory:"):
            with pytest.raises(KsGuardError, match="no database path"):
                KsGuard(url).path

    def test_a_pathless_relative_spelling_is_refused(self) -> None:
        # ``sqlite://localhost`` is the third pathless spelling: the URL names
        # the loopback in the host position and nothing at all in the path.
        # The store's host rule tolerates ``localhost`` (a deployment that
        # spells it out is not a deployment with a remote database), so this
        # is refused as *pathless* rather than as remote — and refused either
        # way, because it names no database to persist a reading in.
        with pytest.raises(KsGuardError, match="no database path"):
            KsGuard("sqlite://localhost").path

    def test_a_remote_sqlite_url_is_refused(self) -> None:
        # SQLite is a file: a URL naming a real host is a misrouted
        # ``DATABASE_URL`` — most likely the Postgres DSN with the wrong
        # scheme — and refusing it here is what keeps the misrouting from
        # surfacing as a mysteriously missing table.
        with pytest.raises(KsGuardError, match="must not carry a host"):
            KsGuard("sqlite://db.internal/nullius.db").path

    def test_an_empty_database_url_is_refused(self, tmp_path: Path) -> None:
        for value in ("", "   "):
            with pytest.raises(KsGuardError, match="non-empty"):
                KsGuard(value)

    def test_a_naive_instant_is_refused_at_the_record(self, tmp_path: Path) -> None:
        # Raised where the value is built rather than at the first comparison
        # that assumes an offset, which would be far from the write that
        # omitted it.
        guard, _ = _store(tmp_path)
        campaign = _campaign(guard)
        null, real, _ = _separated(10)
        with pytest.raises(KsGuardError, match="timezone-aware"):
            guard.guard(
                campaign, null, real, seen_at=datetime(2026, 1, 1, 0, 0, 0)
            )
        assert _guard_rows(guard) == []


# -- The read-back ---------------------------------------------------------------


class TestTheReadRefusesAHalf:
    def test_an_unguarded_campaign_reads_as_none(self, tmp_path: Path) -> None:
        # ``None`` means *the guard has not run for this campaign*, which is
        # the honest answer for a campaign the orchestrator has created and no
        # job has read yet.
        guard, _ = _store(tmp_path)
        campaign = _campaign(guard)
        assert guard.load(campaign) is None

    def test_a_campaign_that_does_not_exist_reads_as_none(
        self, tmp_path: Path
    ) -> None:
        # No campaign, so there is nothing a reading could belong to — the
        # same answer as an unguarded one, from the same place: the
        # orchestrator has not planned it.
        guard, _ = _store(tmp_path)
        assert guard.load(str(uuid.uuid4())) is None

    def test_a_number_without_its_provenance_is_refused(self, tmp_path: Path) -> None:
        # The campaign column filled and the guard row absent: a reader
        # holding the p-value with no way to know the sample sizes it came
        # from. §7.4's number and the provenance it was computed from are one
        # reading's content.
        guard, _ = _store(tmp_path)
        campaign = _campaign(guard)
        with closing(guard._connect()) as connection, connection:
            connection.execute(
                f"UPDATE {CAMPAIGN_TABLE} SET ks_pvalue = ? WHERE id = ?",
                (0.31, campaign),
            )
        with pytest.raises(KsGuardError, match="no guard reading") as raised:
            guard.load(campaign)
        assert "0.31" in str(raised.value)

    def test_provenance_without_the_number_is_refused(self, tmp_path: Path) -> None:
        # The mirror: the guard row holds a reading and the campaign column is
        # NULL, which a reader would take for "not yet tested" — the exact
        # opposite of what the guard row says happened.
        guard, _ = _store(tmp_path)
        campaign = _campaign(guard)
        null, real, _ = _separated(12)
        guard.guard(campaign, null, real)
        with closing(guard._connect()) as connection, connection:
            connection.execute(
                f"UPDATE {CAMPAIGN_TABLE} SET ks_pvalue = NULL WHERE id = ?",
                (campaign,),
            )
        with pytest.raises(KsGuardError, match="may not disagree"):
            guard.load(campaign)

    def test_a_disagreeing_pair_is_refused_rather_than_laundered(
        self, tmp_path: Path
    ) -> None:
        # A tamper, and the reason the read-back exists: §7.4's number is what
        # feature 124 voids a campaign on, so a store that could hand back
        # either half of a disagreeing pair would launder the edit. The
        # campaign row and the guard row are both read and compared, and the
        # edit is named rather than smoothed over.
        guard, _ = _store(tmp_path)
        campaign = _campaign(guard)
        null, real, _ = _separated(12)
        record = guard.guard(campaign, null, real)
        with closing(guard._connect()) as connection, connection:
            connection.execute(
                f"UPDATE {CAMPAIGN_TABLE} SET ks_pvalue = ? WHERE id = ?",
                (0.99, campaign),
            )
        with pytest.raises(KsGuardError, match="may not disagree") as raised:
            guard.load(campaign)
        message = str(raised.value)
        assert "0.99" in message and repr(record.pvalue) in message

    def test_a_corrupted_guard_row_fails_to_reconstruct(self, tmp_path: Path) -> None:
        # The other tamper: the provenance itself edited. The row is rebuilt
        # through the record's own validation, so a p-value outside [0, 1] or
        # a method naming an estimator this member does not carry fails to
        # load rather than arriving as a plausible-looking reading.
        guard, _ = _store(tmp_path)
        campaign = _campaign(guard)
        null, real, _ = _separated(12)
        guard.guard(campaign, null, real)
        with closing(guard._connect()) as connection, connection:
            connection.execute(
                f"UPDATE {KS_GUARD_TABLE} SET method = ? WHERE campaign_id = ?",
                ("approximate", campaign),
            )
        with pytest.raises(KsGuardError, match="method must be"):
            guard.load(campaign)

    def test_an_unparseable_stamp_fails_to_reconstruct(self, tmp_path: Path) -> None:
        guard, _ = _store(tmp_path)
        campaign = _campaign(guard)
        null, real, _ = _separated(12)
        guard.guard(campaign, null, real)
        with closing(guard._connect()) as connection, connection:
            connection.execute(
                f"UPDATE {KS_GUARD_TABLE} SET seen_at = ? WHERE campaign_id = ?",
                ("last Tuesday", campaign),
            )
        with pytest.raises(KsGuardError, match="unparseable stamp"):
            guard.load(campaign)

    def test_a_read_only_operation_leaves_the_reading_alone(
        self, tmp_path: Path
    ) -> None:
        # ``load`` opens the database like every other store in this
        # workspace, which means it ensures the tables exist — so a read of a
        # fresh database must not be mistaken for a write of one.
        guard, _ = _store(tmp_path)
        campaign = _campaign(guard)
        null, real, _ = _separated(12)
        written = guard.guard(campaign, null, real)
        for _ in range(3):
            assert guard.load(campaign) == written
        assert len(_guard_rows(guard)) == 1


# -- The record ------------------------------------------------------------------


class TestTheRecordValidatesItself:
    """A record reconstructed from a stored row passes no factory, so the value
    validates itself — the discipline ``evaluator.identity_from_row`` states
    for the evaluator's hash, applied to §7.4's number.
    """

    def _valid(self, **overrides) -> dict:
        fields = dict(
            campaign_id=str(uuid.uuid4()),
            pvalue=0.31,
            statistic=0.22,
            null_count=30,
            real_count=90,
            method=KS_EXACT,
            seen_at=datetime(2026, 3, 1, tzinfo=timezone.utc),
        )
        fields.update(overrides)
        return fields

    def test_a_valid_record_rebuilds_from_its_payload(self) -> None:
        record = KsGuardRecord(**self._valid())
        payload = record.to_payload()
        assert KsGuardRecord(
            campaign_id=payload["campaign_id"],
            pvalue=payload["pvalue"],
            statistic=payload["statistic"],
            null_count=payload["null_count"],
            real_count=payload["real_count"],
            method=payload["method"],
            seen_at=datetime.fromisoformat(payload["seen_at"]),
        ) == record

    def test_the_measurement_is_derived_and_not_a_second_copy(self) -> None:
        # Re-derived rather than stored, so the record and its measurement can
        # never be two copies that disagree.
        record = KsGuardRecord(**self._valid())
        measurement = record.measurement
        assert measurement.pvalue == record.pvalue
        assert measurement.statistic == record.statistic
        assert measurement.null_count == record.null_count
        assert measurement.real_count == record.real_count
        assert measurement.method == record.method

    def test_a_malformed_campaign_id_is_refused(self) -> None:
        for bad in ("not-a-uuid", None, 17, ""):
            with pytest.raises(KsGuardError, match="is not a UUID"):
                KsGuardRecord(**self._valid(campaign_id=bad))

    def test_a_probability_outside_the_unit_interval_is_refused(self) -> None:
        for name in ("pvalue", "statistic"):
            for bad in (-0.001, 1.5):
                with pytest.raises(KsGuardError, match="must lie in"):
                    KsGuardRecord(**self._valid(**{name: bad}))

    def test_a_non_numeric_probability_is_refused(self) -> None:
        with pytest.raises(KsGuardError, match="must be a real number"):
            KsGuardRecord(**self._valid(pvalue=None))
        with pytest.raises(KsGuardError, match="must be a real number"):
            KsGuardRecord(**self._valid(statistic=True))

    def test_a_non_positive_count_is_refused(self) -> None:
        for name in ("null_count", "real_count"):
            for bad in (0, -1, True, 5.0):
                with pytest.raises(KsGuardError, match="positive integer"):
                    KsGuardRecord(**self._valid(**{name: bad}))

    def test_an_unknown_estimator_is_refused(self) -> None:
        with pytest.raises(KsGuardError, match="method must be"):
            KsGuardRecord(**self._valid(method="bootstrap"))
        assert self._valid(method=KS_ASYMPTOTIC)["method"] == KS_ASYMPTOTIC

    def test_a_naive_instant_is_refused(self) -> None:
        with pytest.raises(KsGuardError, match="timezone-aware"):
            KsGuardRecord(**self._valid(seen_at=datetime(2026, 3, 1)))

    def test_a_non_datetime_instant_is_refused(self) -> None:
        with pytest.raises(KsGuardError, match="must be a datetime"):
            KsGuardRecord(**self._valid(seen_at="2026-03-01T00:00:00+00:00"))

    def test_the_record_is_frozen(self) -> None:
        record = KsGuardRecord(**self._valid())
        with pytest.raises(Exception):
            record.pvalue = 0.9  # type: ignore[misc]

    def test_the_row_rebuilder_reads_the_stores_own_column_order(self) -> None:
        record = KsGuardRecord(**self._valid())
        rebuilt = guard_record_from_row(
            (
                record.campaign_id,
                record.pvalue,
                record.statistic,
                record.null_count,
                record.real_count,
                record.method,
                record.seen_at.isoformat(),
            )
        )
        assert rebuilt == record

    def test_the_row_rebuilder_refuses_a_truncated_row(self) -> None:
        with pytest.raises((ValueError, TypeError)):
            guard_record_from_row(("only", "three", "values"))


# -- The barrier -----------------------------------------------------------------


class TestNothingButCountsIsPersisted:
    """§4.2: ``is_null`` is visible to exactly one component, and §7.4's guard
    job is the sanctioned exception. The store is where that discipline is
    easiest to lose — a column added "for debugging" would leak the partition
    into an artifact the policy can read during replay — so the rule is
    asserted against the table's own bytes, not only against the value the
    caller is handed back.
    """

    def test_no_column_holds_a_score_or_a_node_id(self, tmp_path: Path) -> None:
        guard, _ = _store(tmp_path)
        campaign = _campaign(guard)
        nodes = _nodes(8)
        null = {node: 0.123456789 for node in nodes[:4]}
        real = {node: 987.654321 for node in nodes[4:]}
        guard.guard(campaign, null, real)
        with closing(guard._connect()) as connection:
            cursor = connection.execute(f"SELECT * FROM {KS_GUARD_TABLE}")
            try:
                rows = cursor.fetchall()
            finally:
                cursor.close()
        rendered = repr(rows)
        for node in nodes:
            assert node not in rendered
        assert "0.123456789" not in rendered
        assert "987.654321" not in rendered

    def test_the_record_renders_counts_and_not_the_partition(
        self, tmp_path: Path
    ) -> None:
        guard, _ = _store(tmp_path)
        campaign = _campaign(guard)
        null, real, _ = _separated(16)
        record = guard.guard(campaign, null, real)
        rendered = repr(record) + str(record.to_payload())
        for node in (*null, *real):
            assert node not in rendered
        assert set(record.to_payload()) == {
            "campaign_id",
            "pvalue",
            "statistic",
            "null_count",
            "real_count",
            "method",
            "seen_at",
        }
        assert record.null_count == 16
        assert record.real_count == 16

    def test_the_store_holds_no_sample_between_calls(self, tmp_path: Path) -> None:
        # The mapping the caller hands in goes out of scope with the call:
        # there is no field on the store that could keep it, so a later
        # ``load`` cannot be a way to read the labels back out.
        guard, _ = _store(tmp_path)
        campaign = _campaign(guard)
        null, real, _ = _separated(12)
        guard.guard(campaign, null, real)
        assert not hasattr(guard, "null_scores")
        assert "null_scores" not in vars(guard)
        assert "scores" not in repr(vars(guard))


# -- The schema agreement --------------------------------------------------------


class TestTheStoreAndTheMigrationAgreeOnCampaign:
    """``nulloracle.ksguard``'s module docstring makes this promise: *"The two
    spellings are held together by the columns they name, which is the thing
    they have to agree on — and ``test_ksguard.py`` asserts the agreement
    against the migration's own ``statements('sqlite')``."*  This is that
    assertion.
    """

    def test_the_column_list_matches_the_migration_exactly(
        self, tmp_path: Path
    ) -> None:
        # Not "the columns the store needs are present" — *identical*, in
        # order and in type. A store whose ``campaign`` had an extra column,
        # a retyped one, or a different nullability would be a second schema
        # wearing the migration's table name, and the mismatch would surface
        # only in production, on the dialect the tests do not run.
        migration = _migration()
        guard, _ = _store(tmp_path, "store.db")
        _campaign(guard)
        theirs_path = tmp_path / "migration.db"
        migration.apply(f"sqlite:///{theirs_path}")
        with closing(sqlite3.connect(theirs_path)) as connection:
            cursor = connection.execute(f"PRAGMA table_info({CAMPAIGN_TABLE})")
            try:
                theirs = [
                    (row[1], row[2], row[3], row[4], row[5])
                    for row in cursor.fetchall()
                ]
            finally:
                cursor.close()
        assert _columns(guard, CAMPAIGN_TABLE) == theirs

    def test_the_migrations_own_revision_identity_is_the_one_we_chain_off(
        self, tmp_path: Path
    ) -> None:
        # The store names the migration file it mirrors; this pins that the
        # file it names is the file that creates the table, so a renumbering
        # of the migration tree breaks this test rather than silently
        # detaching the store's docstring from the schema it claims to mirror.
        migration = _migration()
        assert MIGRATION_PATH.name == f"{migration.REVISION}.py"
        assert CAMPAIGN_TABLE in migration.TABLES

    def test_running_the_migration_over_the_stores_database_changes_nothing(
        self, tmp_path: Path
    ) -> None:
        # The contract every store in this workspace states: a fresh database
        # and an existing one take the same path, so no migration step is
        # needed here — and running the migration over a database the store
        # created is a no-op rather than a conflict.
        migration = _migration()
        guard, url = _store(tmp_path)
        campaign = _campaign(guard)
        null, real, _ = _separated(10)
        record = guard.guard(campaign, null, real)
        before = _columns(guard, CAMPAIGN_TABLE)
        migration.apply(url)
        assert _columns(guard, CAMPAIGN_TABLE) == before
        assert guard.load(campaign) == record

    def test_the_guard_works_against_a_migration_created_table(
        self, tmp_path: Path
    ) -> None:
        # The *production* ordering, which the reverse test above does not
        # cover: a migration runner applies ``0111`` first, the orchestrator
        # plans a campaign against the table it created, and only then does
        # §7.4's guard job run.  Every other test in this suite lets the store
        # create the table itself — which it can, idempotently — so without
        # this one the suite would pass for a store that only worked on
        # databases it had created, and fail in production where it never
        # does.
        migration = _migration()
        url = f"sqlite:///{tmp_path / 'migrated.db'}"
        migration.apply(url)
        guard = KsGuard(url)

        # The orchestrator plans the campaign: raw insert, its own columns,
        # nothing of the guard's. (``_campaign`` would create the table via
        # the store's connection, which is the thing under test here.)
        campaign = str(uuid.uuid4())
        values = dict(zip(CAMPAIGN_COLUMNS, CAMPAIGN_VALUES))
        with closing(sqlite3.connect(guard.path)) as connection, connection:
            connection.execute(
                f"INSERT INTO {CAMPAIGN_TABLE} (id, {', '.join(values)}) "
                f"VALUES (?, {', '.join('?' * len(values))})",
                (campaign, *values.values()),
            )

        null, real, _ = _separated(20)
        record = guard.guard(campaign, null, real)

        # The number landed on the migration's own column, on a row the
        # guard did not create...
        assert _row(guard, campaign) == (record.pvalue, "ok")
        # ...its planning columns are the planner's, untouched...
        with closing(guard._connect()) as connection:
            cursor = connection.execute(
                f"SELECT campaign_type, workspace_count, null_fraction FROM "
                f"{CAMPAIGN_TABLE} WHERE id = ?",
                (campaign,),
            )
            try:
                assert cursor.fetchone() == CAMPAIGN_VALUES
            finally:
                cursor.close()
        # ...and it reads back as the same reading.
        assert guard.load(campaign) == record

    def test_the_columns_default_is_the_same_v4_uuid_construction(
        self, tmp_path: Path
    ) -> None:
        # The dialect split ``0111`` argues is carried verbatim, so an id
        # minted by the store's table is the same *kind* of value as
        # ``gen_random_uuid()`` returns — the version and variant nibbles are
        # the ones a v4 UUID must carry.
        guard, _ = _store(tmp_path)
        with closing(guard._connect()) as connection, connection:
            connection.execute(
                f"INSERT INTO {CAMPAIGN_TABLE} (campaign_type, "
                "workspace_count, null_fraction) VALUES (?, ?, ?)",
                CAMPAIGN_VALUES,
            )
            cursor = connection.execute(f"SELECT id, created_at FROM {CAMPAIGN_TABLE}")
            try:
                identifier, created_at = cursor.fetchone()
            finally:
                cursor.close()
        parsed = uuid.UUID(identifier)
        assert parsed.version == 4
        assert parsed.variant == uuid.RFC_4122
        datetime.fromisoformat(created_at)  # the strftime default parses

    def test_the_pvalue_column_is_nullable_and_calibration_status_defaults_ok(
        self, tmp_path: Path
    ) -> None:
        # The two column properties feature 123 and 124 lean on: ``ks_pvalue``
        # is Nullable so "not yet read" stays distinguishable from "tested,
        # and decisively detectable", and ``calibration_status`` defaults to
        # 'ok' so a campaign is calibrated by construction until 124 says
        # otherwise.
        guard, _ = _store(tmp_path)
        _campaign(guard)
        columns = {column[0]: column for column in _columns(guard, CAMPAIGN_TABLE)}
        assert columns["ks_pvalue"][2] == 0, "ks_pvalue must be nullable"
        assert columns["calibration_status"][2] == 1
        assert "'ok'" in (columns["calibration_status"][3] or "")


# -- Resolution ------------------------------------------------------------------


class TestTheStoreResolvesLikeEveryOtherStore:
    def test_unset_names_no_store(self) -> None:
        assert KsGuard.resolve({}) is None
        assert KsGuard.resolve({DATABASE_URL_ENV: ""}) is None
        assert KsGuard.resolve({DATABASE_URL_ENV: "   "}) is None

    def test_a_named_store_resolves(self, tmp_path: Path) -> None:
        url = f"sqlite:///{tmp_path / 'store.db'}"
        guard = KsGuard.resolve({DATABASE_URL_ENV: url})
        assert guard is not None
        assert guard.database_url == url

    def test_resolution_performs_no_io(self, tmp_path: Path) -> None:
        # Composition-time work must not touch the disk: resolving the
        # component is what the factory does for every app it builds, and a
        # member that created a database on import would put a file in the
        # path of every test that merely composed the app.
        path = tmp_path / "never" / "store.db"
        guard = KsGuard.resolve({DATABASE_URL_ENV: f"sqlite:///{path}"})
        assert guard is not None
        assert guard.database_url  # reading the URL resolves nothing
        assert guard.path == path
        assert not path.exists()
        assert not path.parent.exists()

    def test_a_relative_path_translates_and_percent_escaping_is_undone(
        self, tmp_path: Path
    ) -> None:
        assert KsGuard("sqlite:///lake/null.db").path == Path("lake/null.db")
        assert KsGuard("sqlite:///lake/a%20b.db").path == Path("lake/a b.db")

    def test_the_module_level_write_refuses_when_nothing_names_a_store(self) -> None:
        # A guard that quietly skipped its write would leave a campaign
        # looking un-read while §7.4's job believed it had run — the failure
        # this whole feature exists to rule out. So the refusal is by name.
        with pytest.raises(KsGuardError, match="names a store") as raised:
            persist_ks_pvalue(str(uuid.uuid4()), [1.0, 2.0], [3.0, 4.0])
        assert DATABASE_URL_ENV in str(raised.value)
        with pytest.raises(KsGuardError, match="names a store"):
            persist_ks_pvalue(
                str(uuid.uuid4()), [1.0, 2.0], [3.0, 4.0], env={DATABASE_URL_ENV: ""}
            )

    def test_the_module_level_spellings_are_the_store_s_own(
        self, tmp_path: Path
    ) -> None:
        url = f"sqlite:///{tmp_path / 'store.db'}"
        guard = KsGuard(url)
        campaign = _campaign(guard)
        null, real, _ = _separated(20)
        written = persist_ks_pvalue(
            campaign, null, real, database_url=url
        )
        assert written == guard.load(campaign)
        assert load_ks_guard(campaign, database_url=url) == written
        assert load_ks_guard(campaign, env={DATABASE_URL_ENV: url}) == written

    def test_the_module_level_read_answers_none_without_a_store(self) -> None:
        # The same "no store, no reading" answer ``KsGuard.load`` gives for an
        # unguarded campaign — kept distinct in the store's own documentation
        # because a caller that mistook an unconfigured deployment for an
        # unguarded campaign would skip §7.4's guard entirely.
        assert load_ks_guard(str(uuid.uuid4())) is None
        assert load_ks_guard(str(uuid.uuid4()), env={}) is None


# -- The module ------------------------------------------------------------------


class TestTheStoreModuleIsStdlibOnlyAndImportCheap:
    def test_no_third_party_import_at_module_scope(self) -> None:
        # The member already defers ``cryptography`` to first use, and a store
        # that pulled a driver in at import would undo that — the factory's
        # scan imports this package to fire its ``@register``, so every app
        # would pay for it.
        import nulloracle.ksguard as module

        source = Path(module.__file__).read_text(encoding="utf-8")
        for banned in ("import sqlalchemy", "import psycopg", "import numpy"):
            assert banned not in source

    def test_the_module_never_writes_the_verdict_column(self, tmp_path: Path) -> None:
        # §7.4's ``VOID`` is feature 124's write, and this asserts it on every
        # statement the module reaches a database with rather than on the one
        # path today's tests walk: a ``SET calibration_status`` added inside a
        # branch no test exercises would be a threshold nobody could audit,
        # and would be invisible to the behavioural test above.
        #
        # The statements are *traced*, not scanned for in the source text: the
        # module docstring argues this exact boundary at length — that is
        # where the decision is explained — so a substring search over the
        # file cannot tell a sentence about ``calibration_status`` from a
        # write to it.
        import nulloracle.ksguard as module

        statements: list[str] = []

        class _Traced(sqlite3.Connection):
            def execute(self, statement, *args, **kwargs):  # type: ignore[no-untyped-def]
                statements.append(statement)
                return super().execute(statement, *args, **kwargs)

            def executescript(self, script):  # type: ignore[no-untyped-def]
                statements.append(script)
                return super().executescript(script)

        original = module.sqlite3.connect
        module.sqlite3.connect = lambda path: original(path, factory=_Traced)
        try:
            guard, _ = _store(tmp_path)
            campaign = _campaign(guard)
            null, real, _ = _separated(10)
            guard.guard(campaign, null, real)
            guard.load(campaign)
        finally:
            module.sqlite3.connect = original

        # The trace is a real one: the statements this feature's write path
        # issues are in it, so an empty verdict-write list means what it says.
        assert any("INSERT INTO campaign_ks_guard" in s for s in statements)
        assert any(s.lstrip().startswith("UPDATE campaign") for s in statements)
        assert [
            s
            for s in statements
            if "SET" in s.upper() and "calibration_status" in s
        ] == []
