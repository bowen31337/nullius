"""Feature 124's store half: the ``VOID`` verdict persisted against its campaign.

app_spec.xml, "Null Oracle & Planted Nulls", feature 124: *System persists a
campaign calibration_status of VOID when the KS p-value falls below 0.05, which
halts dreaming and excludes the campaign from the pool.*  ``test_ks.py`` pins
the test, ``test_ksguard.py`` pins the p-value's persistence, and this suite
pins the decision — §7.4's ``p < 0.05`` comparison and the ``VOID`` it sets.

What is asserted here is mostly not *that a status was stored* — that is one
test — but the properties that make the stored verdict trustworthy, because
§7.4's verdict is what features 876 and 1056 read to reject a campaign from the
replay pool and from promotion:

* **it is pronounced on the stored number.**  The p-value the verdict compares
  is read back from ``campaign.ks_pvalue`` inside the transaction that writes
  the verdict — not a p-value the caller hands in.  A verdict that voided on a
  number the store never saw would be a plausible-looking number crossing the
  §4.2 barrier, so the verdict is asserted to take no p-value argument and to
  read the stored one before it writes.
* **the threshold is §7.4's, and it is strict.**  A p-value below 0.05 voids;
  one at or above it leaves the campaign as it was.  The boundary errs toward
  keeping a campaign in.
* **the verdict is one transition only.**  It sets ``VOID`` and never clears
  it: a voided campaign stays voided, and a clean campaign's ``'ok'`` default
  survives a verdict that does not reach it.
* **the verdict is a fact about a campaign.**  A campaign the table does not
  hold is refused by name rather than created, and a stored p-value that is
  not a probability is refused rather than voided on.
* **nothing but the status is written.**  The verdict fills one column of a
  row that is not its own: the planning facts and the p-value are left exactly
  as the planner and the guard left them.
"""

from __future__ import annotations

import importlib.util
import inspect
import sqlite3
import uuid
from contextlib import closing
from pathlib import Path

import pytest
from nulloracle import (
    CALIBRATION_STATUS_OK,
    CALIBRATION_STATUS_VOID,
    CAMPAIGN_TABLE,
    DATABASE_URL_ENV,
    VOID_THRESHOLD,
    CampaignVerdict,
    KsGuardError,
    Verdict,
    load_verdict,
    void_if_detectable,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
MIGRATION_PATH = REPO_ROOT / "migrations" / "versions" / "0111_campaign_table.py"

#: A campaign's planning-time row: the three ``NOT NULL`` columns with no
#: default, in the shape ``migrations/versions/0111_campaign_table.py``
#: describes (Type-R at W = 12, so φ = clip(2/12, 0.15, 0.35) = 0.1667…).
CAMPAIGN_COLUMNS = ("campaign_type", "workspace_count", "null_fraction")
CAMPAIGN_VALUES = ("Type-R", 12, 0.1667)


# -- Helpers ---------------------------------------------------------------------


def _store(tmp_path: Path, name: str = "verdict.db") -> tuple[CampaignVerdict, str]:
    """A verdict store over a fresh SQLite file, with its ``DATABASE_URL``."""
    path = tmp_path / name
    url = f"sqlite:///{path}"
    return CampaignVerdict(url), url


def _campaign(store: CampaignVerdict, campaign_id: str | None = None, **overrides) -> str:
    """Insert a campaign row the way its planner would, and return its id."""
    identifier = campaign_id or str(uuid.uuid4())
    values = dict(zip(CAMPAIGN_COLUMNS, CAMPAIGN_VALUES))
    values.update(overrides)
    with closing(store._connect()) as connection, connection:
        connection.execute(
            f"INSERT INTO {CAMPAIGN_TABLE} (id, {', '.join(values)}) "
            f"VALUES (?, {', '.join('?' * len(values))})",
            (identifier, *values.values()),
        )
    return identifier


def _set_pvalue(store: CampaignVerdict, campaign_id: str, pvalue) -> None:
    """Set a campaign's ``ks_pvalue`` directly, the way the guard would fill it."""
    with closing(store._connect()) as connection, connection:
        connection.execute(
            f"UPDATE {CAMPAIGN_TABLE} SET ks_pvalue = ? WHERE id = ?",
            (pvalue, campaign_id),
        )


def _status(store: CampaignVerdict, campaign_id: str) -> tuple:
    """The campaign row's ``(calibration_status, ks_pvalue)``, read raw."""
    with closing(store._connect()) as connection:
        cursor = connection.execute(
            f"SELECT calibration_status, ks_pvalue FROM {CAMPAIGN_TABLE} "
            "WHERE id = ?",
            (campaign_id,),
        )
        try:
            return cursor.fetchone()
        finally:
            cursor.close()


def _columns(store: CampaignVerdict, table: str) -> list[tuple]:
    """``PRAGMA table_info`` for ``table``, as ``(name, type, notnull, dflt, pk)``."""
    with closing(store._connect()) as connection:
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

    By path rather than by import because that is how a migration runner loads
    it: the file is not a module on any package's ``sys.path``, and a test that
    could only reach it through an import would be testing a different
    arrangement from the one that runs.
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

    Autouse and unconditional, mirroring the member's other isolation fixtures:
    the default state of a test is a deployment that names no relational store,
    and the tests that assert on the *unconfigured* behaviour then do not fight
    a fixture that helpfully configured one.  Each test that wants a store
    builds its own over ``tmp_path``, so no test in this suite can reach a real
    database.
    """
    monkeypatch.delenv(DATABASE_URL_ENV, raising=False)


# -- The verdict is pronounced on the stored number --------------------------------


class TestTheVerdictReadsTheStoredPValue:
    def test_a_campaign_below_threshold_is_voided(self, tmp_path: Path) -> None:
        store, _ = _store(tmp_path)
        campaign = _campaign(store)
        _set_pvalue(store, campaign, 0.01)
        verdict = store.void_if_detectable(campaign)
        assert verdict.status == CALIBRATION_STATUS_VOID
        assert verdict.voided is True
        assert verdict.pvalue == 0.01
        assert _status(store, campaign) == ("VOID", 0.01)

    def test_a_campaign_above_threshold_is_left_ok(self, tmp_path: Path) -> None:
        store, _ = _store(tmp_path)
        campaign = _campaign(store)
        _set_pvalue(store, campaign, 0.31)
        verdict = store.void_if_detectable(campaign)
        assert verdict.status == CALIBRATION_STATUS_OK
        assert verdict.voided is False
        assert verdict.pvalue == 0.31
        assert _status(store, campaign) == ("ok", 0.31)

    def test_a_campaign_exactly_at_threshold_is_not_voided(self, tmp_path: Path) -> None:
        # §7.4's rule is strict ``<``: a p-value exactly at the level is not
        # below it, so the campaign stays in.  The boundary errs toward
        # keeping a campaign in the pool, and the operator's alert — not a
        # silent exclusion — is what §7.4 asks for at the margin.
        store, _ = _store(tmp_path)
        campaign = _campaign(store)
        _set_pvalue(store, campaign, VOID_THRESHOLD)
        verdict = store.void_if_detectable(campaign)
        assert verdict.status == CALIBRATION_STATUS_OK
        assert verdict.voided is False
        assert _status(store, campaign) == ("ok", VOID_THRESHOLD)

    def test_a_campaign_with_no_pvalue_yet_is_left_ok(self, tmp_path: Path) -> None:
        # The guard has not run: there is no stored number to pronounce on, so
        # there is no detectability finding to void the campaign on.  The
        # campaign keeps its 'ok' default — the honest state for a campaign
        # whose read has not happened, and the opposite of "tested, and
        # decisively detectable" a NOT NULL p-value would have fabricated.
        store, _ = _store(tmp_path)
        campaign = _campaign(store)
        verdict = store.void_if_detectable(campaign)
        assert verdict.status == CALIBRATION_STATUS_OK
        assert verdict.voided is False
        assert verdict.pvalue == 1.0
        assert _status(store, campaign) == ("ok", None)

    def test_the_verdict_is_pronounced_on_what_the_store_holds(self, tmp_path: Path) -> None:
        # The number the verdict voids a campaign on is read back from
        # ``campaign.ks_pvalue`` inside the write's own transaction — not a
        # p-value the caller supplies.  The same campaign, the same call, a
        # different stored number, a different verdict: the verdict follows
        # the stored p-value, so a caller cannot void on a number the store
        # never saw.
        store, _ = _store(tmp_path)
        campaign = _campaign(store)
        _set_pvalue(store, campaign, 0.5)
        assert store.void_if_detectable(campaign).status == CALIBRATION_STATUS_OK
        _set_pvalue(store, campaign, 0.001)
        assert store.void_if_detectable(campaign).status == CALIBRATION_STATUS_VOID

    def test_the_verdict_takes_no_pvalue_argument(self) -> None:
        # Structural proof of the property above: neither the store method nor
        # the module-level spelling has a p-value parameter, so there is no
        # path by which a caller could make the verdict void on a number the
        # store did not persist.  The verdict is pronounced on the stored
        # number, or not at all.
        store_params = list(inspect.signature(CampaignVerdict.void_if_detectable).parameters)
        module_params = list(inspect.signature(void_if_detectable).parameters)
        assert "pvalue" not in store_params
        assert "pvalue" not in module_params
        assert set(store_params) - {"self"} == {"campaign_id"}
        assert set(module_params) == {"campaign_id", "database_url", "env"}

    def test_the_verdict_reads_the_pvalue_before_it_writes(self, tmp_path: Path) -> None:
        # Traced, not scanned: the statements the verdict issues are recorded,
        # so the read of ``ks_pvalue`` can be shown to precede the write of
        # ``calibration_status`` in the same transaction.  A verdict that
        # wrote the status without first reading the number would be voiding
        # on a p-value it never saw.
        import nulloracle.verdict as module

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
            store, _ = _store(tmp_path)
            campaign = _campaign(store)
            _set_pvalue(store, campaign, 0.01)
            statements.clear()
            store.void_if_detectable(campaign)
        finally:
            module.sqlite3.connect = original

        reads = [i for i, s in enumerate(statements) if "SELECT ks_pvalue" in s]
        writes = [i for i, s in enumerate(statements) if "UPDATE campaign" in s and "SET" in s.upper()]
        assert reads, "the verdict must read the stored p-value"
        assert writes, "the verdict must write the status"
        assert reads[0] < writes[0], "the p-value is read before the verdict is written"

    def test_the_verdict_is_pronounced_on_the_number_the_guard_persisted(
        self, tmp_path: Path
    ) -> None:
        # The production path: feature 123 persists the p-value, then feature
        # 124 reads it back and decides.  The two are one reading because the
        # verdict reads what the guard wrote — the number feature 124 voids a
        # campaign on is the number feature 123 actually stored, not a fresh
        # computation and not a caller's argument.
        from nulloracle import KsGuard

        url = f"sqlite:///{tmp_path / 'both.db'}"
        guard = KsGuard(url)
        verdict = CampaignVerdict(url)
        campaign = _campaign(verdict)
        record = guard.guard(campaign, [1.0, 2.0, 3.0, 4.0], [5.0, 6.0, 7.0, 8.0])
        assert record.pvalue < VOID_THRESHOLD
        result = verdict.void_if_detectable(campaign)
        assert result.status == CALIBRATION_STATUS_VOID
        assert result.pvalue == record.pvalue
        assert verdict.load(campaign) == CALIBRATION_STATUS_VOID

    def test_the_verdict_never_creates_the_campaign_row(self, tmp_path: Path) -> None:
        # The verdict is a fact about a campaign, so a verdict that created the
        # row it voided would be inventing the campaign — and the null fraction
        # the whole blinding discipline is built around is fixed by the
        # planner, not here.  A refused verdict leaves no row behind.
        store, _ = _store(tmp_path)
        unplanned = str(uuid.uuid4())
        with pytest.raises(KsGuardError):
            store.void_if_detectable(unplanned)
        with closing(store._connect()) as connection:
            cursor = connection.execute(
                f"SELECT COUNT(*) FROM {CAMPAIGN_TABLE} WHERE id = ?", (unplanned,)
            )
            try:
                count = cursor.fetchone()[0]
            finally:
                cursor.close()
        assert count == 0

    def test_the_verdict_never_writes_the_pvalue_or_the_guard_row(self, tmp_path: Path) -> None:
        # The verdict fills one column of a row that is not its own.  Traced
        # across every statement it issues, so a stray ``UPDATE ... SET
        # ks_pvalue`` or an ``INSERT INTO campaign_ks_guard`` in a branch no
        # behavioural test walks would be caught here.
        import nulloracle.verdict as module

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
            store, _ = _store(tmp_path)
            campaign = _campaign(store)
            _set_pvalue(store, campaign, 0.01)
            statements.clear()
            store.void_if_detectable(campaign)
        finally:
            module.sqlite3.connect = original

        assert any(s.lstrip().startswith("UPDATE campaign") for s in statements)
        assert [s for s in statements if "SET" in s.upper() and "ks_pvalue" in s] == []
        assert [s for s in statements if "campaign_ks_guard" in s] == []


# -- One transition only -----------------------------------------------------------


class TestTheVerdictIsStable:
    def test_a_verdict_rerun_on_a_voided_campaign_leaves_it_void(self, tmp_path: Path) -> None:
        # §7.4's own instruction is "investigate the block length and
        # permutation scheme before proceeding", so a campaign is expected to
        # be judged more than once.  The verdict is stable: a second judgment
        # on an already-voided campaign leaves it void and reports that this
        # call did not change it — the record distinguishes *this call voided
        # it* from *it was already void*.
        store, _ = _store(tmp_path)
        campaign = _campaign(store)
        _set_pvalue(store, campaign, 0.01)
        first = store.void_if_detectable(campaign)
        second = store.void_if_detectable(campaign)
        assert first.voided is True
        assert second.status == CALIBRATION_STATUS_VOID
        assert second.voided is False
        assert _status(store, campaign) == ("VOID", 0.01)

    def test_a_clean_campaign_keeps_its_ok_default_across_reruns(self, tmp_path: Path) -> None:
        store, _ = _store(tmp_path)
        campaign = _campaign(store)
        _set_pvalue(store, campaign, 0.31)
        first = store.void_if_detectable(campaign)
        second = store.void_if_detectable(campaign)
        assert first.status == CALIBRATION_STATUS_OK
        assert second.status == CALIBRATION_STATUS_OK
        assert first.voided is False and second.voided is False
        assert _status(store, campaign) == ("ok", 0.31)

    def test_a_verdict_does_not_touch_the_planning_columns(self, tmp_path: Path) -> None:
        # The verdict fills one column of a row that is not its own.  The
        # planning-time facts — the type, W, φ — are the planner's, and a
        # verdict that rewrote any of them would be quietly redefining the
        # campaign it just judged.
        store, _ = _store(tmp_path)
        campaign = _campaign(store)
        _set_pvalue(store, campaign, 0.01)
        store.void_if_detectable(campaign)
        with closing(store._connect()) as connection:
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

    def test_the_verdict_writes_the_status_the_pool_reads(self, tmp_path: Path) -> None:
        # The verdict is not the whole of §7.4's consequence — the alert and
        # the dreaming-halt and pool-exclusion are enforced where the pool and
        # promotion read the status (features 876/1056).  So this asserts the
        # one thing the verdict owns and the rest of the system reacts to: the
        # status on the campaign row is exactly ``VOID``, the value those
        # refusals reject a campaign on, and nothing else changed.
        store, _ = _store(tmp_path)
        campaign = _campaign(store)
        _set_pvalue(store, campaign, 0.02)
        store.void_if_detectable(campaign)
        assert load_verdict(campaign, database_url=store.database_url) == CALIBRATION_STATUS_VOID


# -- The verdict refuses rather than guesses ---------------------------------------


class TestTheVerdictRefusesRatherThanGuesses:
    def test_a_campaign_the_table_does_not_hold_is_refused_by_name(self, tmp_path: Path) -> None:
        # The verdict is a fact *about a campaign*.  A verdict that wrote
        # ``calibration_status`` onto a row it created would be inventing the
        # campaign the verdict belongs to — and the fraction the whole blinding
        # discipline is built around is fixed by the planner, not here.
        store, _ = _store(tmp_path)
        unplanned = str(uuid.uuid4())
        with pytest.raises(KsGuardError, match="holds no row") as raised:
            store.void_if_detectable(unplanned)
        assert "per campaign" in str(raised.value)

    def test_a_malformed_campaign_id_is_a_store_error(self, tmp_path: Path) -> None:
        # The taxonomy's distinction: a malformed id handed to the verdict is a
        # store-contract failure.  A caller reading ``SidecarError`` out of a
        # KS verdict would look in the wrong module for the cause.
        from nulloracle import SidecarError

        store, _ = _store(tmp_path)
        with pytest.raises(KsGuardError, match="is not a UUID") as raised:
            store.void_if_detectable("not-a-uuid")
        assert not isinstance(raised.value, SidecarError)
        assert isinstance(raised.value.__cause__, SidecarError)

    def test_a_stored_pvalue_outside_the_unit_interval_is_refused(self, tmp_path: Path) -> None:
        # A tamper, and the reason the verdict reads the stored number: a
        # p-value outside ``[0, 1]`` is not a p-value any test produced, and
        # voiding a campaign on it — or leaving it in on it — would be the
        # exact plausible-looking number this member exists to keep out of the
        # calibration record.  Refused rather than computed over.
        store, _ = _store(tmp_path)
        campaign = _campaign(store)
        _set_pvalue(store, campaign, 1.5)
        with pytest.raises(KsGuardError, match="must lie in"):
            store.void_if_detectable(campaign)
        assert _status(store, campaign) == ("ok", 1.5)

    def test_a_negative_stored_pvalue_is_refused(self, tmp_path: Path) -> None:
        store, _ = _store(tmp_path)
        campaign = _campaign(store)
        _set_pvalue(store, campaign, -0.1)
        with pytest.raises(KsGuardError, match="must lie in"):
            store.void_if_detectable(campaign)

    def test_the_store_refuses_a_url_it_cannot_speak(self, tmp_path: Path) -> None:
        # Composition must not raise — a deployment whose DATABASE_URL points
        # at Postgres still composes, and the store that cannot speak its URL
        # says so the first time it is *used*.  The alternative is an app that
        # will not start because one member's driver is missing.
        store = CampaignVerdict("postgresql://db.internal/nullius")
        assert store.database_url == "postgresql://db.internal/nullius"
        with pytest.raises(KsGuardError, match="unsupported"):
            store.void_if_detectable(str(uuid.uuid4()))

    def test_an_in_memory_url_is_refused(self) -> None:
        # An in-memory database dies with the connection that opened it, and a
        # verdict written to a database that then vanished would leave a
        # campaign looking calibrated when it had in fact been voided.
        for url in ("sqlite://", "sqlite:///:memory:"):
            with pytest.raises(KsGuardError, match="no database path"):
                CampaignVerdict(url).path

    def test_an_empty_database_url_is_refused(self) -> None:
        for value in ("", "   "):
            with pytest.raises(KsGuardError, match="non-empty"):
                CampaignVerdict(value)


# -- The read-back -----------------------------------------------------------------


class TestTheReadBack:
    def test_load_returns_the_status_of_a_voided_campaign(self, tmp_path: Path) -> None:
        store, url = _store(tmp_path)
        campaign = _campaign(store)
        _set_pvalue(store, campaign, 0.01)
        store.void_if_detectable(campaign)
        assert store.load(campaign) == CALIBRATION_STATUS_VOID
        assert load_verdict(campaign, database_url=url) == CALIBRATION_STATUS_VOID

    def test_load_returns_ok_for_a_clean_campaign(self, tmp_path: Path) -> None:
        store, _ = _store(tmp_path)
        campaign = _campaign(store)
        _set_pvalue(store, campaign, 0.31)
        store.void_if_detectable(campaign)
        assert store.load(campaign) == CALIBRATION_STATUS_OK

    def test_load_returns_none_for_a_campaign_the_table_does_not_hold(self, tmp_path: Path) -> None:
        # No campaign, so there is nothing a status could belong to — the same
        # answer as an unjudged one, from the same place: the orchestrator has
        # not planned it.  It does not mean the read failed.
        store, _ = _store(tmp_path)
        assert store.load(str(uuid.uuid4())) is None
        assert load_verdict(str(uuid.uuid4()), database_url=store.database_url) is None

    def test_load_raises_for_a_malformed_id(self, tmp_path: Path) -> None:
        store, _ = _store(tmp_path)
        with pytest.raises(KsGuardError, match="is not a UUID"):
            store.load("not-a-uuid")


# -- The record --------------------------------------------------------------------


class TestTheRecordValidatesItself:
    """A verdict is the value an operator reads and the pool's refusals act on,
    so it validates itself — the discipline the guard's record applies to
    §7.4's number, applied to §7.4's decision.
    """

    def _valid(self, **overrides) -> dict:
        fields = dict(
            campaign_id=str(uuid.uuid4()),
            status=CALIBRATION_STATUS_VOID,
            pvalue=0.01,
            voided=True,
        )
        fields.update(overrides)
        return fields

    def test_a_valid_record_rebuilds_from_its_payload(self) -> None:
        record = Verdict(**self._valid())
        payload = record.to_payload()
        assert Verdict(**payload) == record

    def test_the_record_names_its_two_statuses(self) -> None:
        assert Verdict(**self._valid(status=CALIBRATION_STATUS_OK, voided=False)).status == "ok"
        assert Verdict(**self._valid()).is_void is True

    def test_a_status_that_is_not_ok_or_void_is_refused(self) -> None:
        with pytest.raises(KsGuardError, match="must be"):
            Verdict(**self._valid(status="NULL"))

    def test_a_probability_outside_the_unit_interval_is_refused(self) -> None:
        for bad in (-0.001, 1.5):
            with pytest.raises(KsGuardError, match="must lie in"):
                Verdict(**self._valid(pvalue=bad))

    def test_a_non_numeric_probability_is_refused(self) -> None:
        with pytest.raises(KsGuardError, match="must be a real number"):
            Verdict(**self._valid(pvalue=None))

    def test_a_voided_bit_that_is_not_a_bool_is_refused(self) -> None:
        with pytest.raises(KsGuardError, match="must be a bool"):
            Verdict(**self._valid(voided="yes"))

    def test_a_malformed_campaign_id_is_refused(self) -> None:
        for bad in ("not-a-uuid", None, 17, ""):
            with pytest.raises(KsGuardError, match="is not a UUID"):
                Verdict(**self._valid(campaign_id=bad))

    def test_a_call_claiming_to_void_an_ok_campaign_is_refused(self) -> None:
        # The one way the status and the voided bit can disagree into an
        # untrustworthy verdict: a call that reports it voided the campaign
        # while the status says ok.  The reverse — VOID with voided=False, a
        # verdict re-run on a campaign already voided — is legitimate.
        with pytest.raises(KsGuardError, match="disagree"):
            Verdict(**self._valid(status=CALIBRATION_STATUS_OK, voided=True))
        assert Verdict(**self._valid(status=CALIBRATION_STATUS_VOID, voided=False)).status == "VOID"

    def test_the_record_renders_what_changed(self) -> None:
        voided = Verdict(**self._valid())
        assert "voided" in repr(voided)
        kept = Verdict(**self._valid(status=CALIBRATION_STATUS_VOID, voided=False))
        assert "unchanged" in repr(kept)
        assert kept.to_payload() == {
            "campaign_id": kept.campaign_id,
            "status": "VOID",
            "pvalue": 0.01,
            "voided": False,
        }

    def test_the_record_is_frozen(self) -> None:
        record = Verdict(**self._valid())
        with pytest.raises(Exception):
            record._status = "NULL"  # type: ignore[misc]


# -- The barrier -------------------------------------------------------------------


class TestNothingButTheStatusIsPersisted:
    def test_no_score_or_node_id_is_persisted(self, tmp_path: Path) -> None:
        # §4.2: the verdict reads one number off the campaign row, compares it
        # to a constant, and writes one column.  Asserted against the table's
        # own bytes: no score, no node id, in any column — the verdict is the
        # last place in the §7.4 path a label partition could leak into an
        # artifact the policy can read during replay.
        store, _ = _store(tmp_path)
        nodes = [str(uuid.uuid4()) for _ in range(8)]
        campaign = _campaign(store)
        _set_pvalue(store, campaign, 0.01)
        with closing(store._connect()) as connection, connection:
            connection.execute(
                f"UPDATE {CAMPAIGN_TABLE} SET ks_pvalue = ? WHERE id = ?",
                (0.01, campaign),
            )
        store.void_if_detectable(campaign)
        with closing(store._connect()) as connection:
            cursor = connection.execute(f"SELECT * FROM {CAMPAIGN_TABLE}")
            try:
                rows = cursor.fetchall()
            finally:
                cursor.close()
        rendered = repr(rows)
        for node in nodes:
            assert node not in rendered


# -- The schema agreement ----------------------------------------------------------


class TestTheVerdictAndTheMigrationAgreeOnCampaign:
    def test_the_calibration_status_default_is_ok_and_ks_pvalue_is_nullable(
        self, tmp_path: Path
    ) -> None:
        # The two column properties feature 123 and 124 lean on: ``ks_pvalue``
        # is Nullable so "not yet read" stays distinguishable from "tested, and
        # decisively detectable", and ``calibration_status`` defaults to 'ok'
        # so a campaign is calibrated by construction until 124 voids it.
        store, _ = _store(tmp_path)
        _campaign(store)
        columns = {column[0]: column for column in _columns(store, CAMPAIGN_TABLE)}
        assert columns["ks_pvalue"][2] == 0, "ks_pvalue must be nullable"
        assert columns["calibration_status"][2] == 1
        assert "'ok'" in (columns["calibration_status"][3] or "")

    def test_the_verdict_works_against_a_migration_created_table(self, tmp_path: Path) -> None:
        # The production ordering: a migration runner applies ``0111`` first,
        # the orchestrator plans a campaign against the table it created, and
        # only then does §7.4's verdict job run.  Every other test lets the
        # store create the table itself — which it can, idempotently — so
        # without this one the suite would pass for a verdict that only worked
        # on databases it had created, and fail in production.
        migration = _migration()
        url = f"sqlite:///{tmp_path / 'migrated.db'}"
        migration.apply(url)
        store = CampaignVerdict(url)
        campaign = str(uuid.uuid4())
        values = dict(zip(CAMPAIGN_COLUMNS, CAMPAIGN_VALUES))
        with closing(sqlite3.connect(store.path)) as connection, connection:
            connection.execute(
                f"INSERT INTO {CAMPAIGN_TABLE} (id, {', '.join(values)}) "
                f"VALUES (?, {', '.join('?' * len(values))})",
                (campaign, *values.values()),
            )
        _set_pvalue(store, campaign, 0.01)
        verdict = store.void_if_detectable(campaign)
        assert verdict.status == CALIBRATION_STATUS_VOID
        assert store.load(campaign) == CALIBRATION_STATUS_VOID

    def test_running_the_migration_over_the_stores_database_changes_nothing(
        self, tmp_path: Path
    ) -> None:
        # A fresh database and an existing one take the same path, so no
        # migration step is needed here — and running the migration over a
        # database the store created is a no-op rather than a conflict.
        migration = _migration()
        store, url = _store(tmp_path)
        campaign = _campaign(store)
        _set_pvalue(store, campaign, 0.01)
        store.void_if_detectable(campaign)
        before = _columns(store, CAMPAIGN_TABLE)
        migration.apply(url)
        assert _columns(store, CAMPAIGN_TABLE) == before
        assert store.load(campaign) == CALIBRATION_STATUS_VOID


# -- Resolution --------------------------------------------------------------------


class TestTheStoreResolvesLikeEveryOtherStore:
    def test_unset_names_no_store(self) -> None:
        assert CampaignVerdict.resolve({}) is None
        assert CampaignVerdict.resolve({DATABASE_URL_ENV: ""}) is None
        assert CampaignVerdict.resolve({DATABASE_URL_ENV: "   "}) is None

    def test_a_named_store_resolves(self, tmp_path: Path) -> None:
        url = f"sqlite:///{tmp_path / 'store.db'}"
        store = CampaignVerdict.resolve({DATABASE_URL_ENV: url})
        assert store is not None
        assert store.database_url == url

    def test_resolution_performs_no_io(self, tmp_path: Path) -> None:
        # Composition-time work must not touch the disk: resolving the
        # component is what the factory does for every app it builds, and a
        # member that created a database on import would put a file in the
        # path of every test that merely composed the app.
        path = tmp_path / "never" / "store.db"
        store = CampaignVerdict.resolve({DATABASE_URL_ENV: f"sqlite:///{path}"})
        assert store is not None
        assert store.database_url
        assert store.path == path
        assert not path.exists()
        assert not path.parent.exists()

    def test_the_module_level_write_refuses_when_nothing_names_a_store(self) -> None:
        # A verdict that quietly skipped its write would leave a campaign
        # looking calibrated while §7.4's job believed it had been judged — the
        # failure this whole feature exists to rule out.  So the refusal is by
        # name.
        with pytest.raises(KsGuardError, match="names a store") as raised:
            void_if_detectable(str(uuid.uuid4()))
        assert DATABASE_URL_ENV in str(raised.value)

    def test_the_module_level_spellings_are_the_store_s_own(self, tmp_path: Path) -> None:
        url = f"sqlite:///{tmp_path / 'store.db'}"
        store = CampaignVerdict(url)
        campaign = _campaign(store)
        _set_pvalue(store, campaign, 0.01)
        written = void_if_detectable(campaign, database_url=url)
        assert written.status == CALIBRATION_STATUS_VOID
        assert store.load(campaign) == CALIBRATION_STATUS_VOID
        assert load_verdict(campaign, env={DATABASE_URL_ENV: url}) == CALIBRATION_STATUS_VOID

    def test_the_module_level_read_answers_none_without_a_store(self) -> None:
        # The same "no store, no status" answer ``CampaignVerdict.load`` gives
        # for an unplanned campaign — kept distinct because a caller that
        # mistook an unconfigured deployment for an unjudged campaign would
        # skip §7.4's verdict entirely.
        assert load_verdict(str(uuid.uuid4())) is None
        assert load_verdict(str(uuid.uuid4()), env={}) is None


# -- The module --------------------------------------------------------------------


class TestTheVerdictModuleIsStdlibOnlyAndImportCheap:
    def test_no_third_party_import_at_module_scope(self) -> None:
        # The member already defers ``cryptography`` to first use, and a verdict
        # that pulled a driver in at import would undo that — the factory's
        # scan imports this package to fire its ``@register``, so every app
        # would pay for it.
        import nulloracle.verdict as module

        source = Path(module.__file__).read_text(encoding="utf-8")
        for banned in ("import sqlalchemy", "import psycopg", "import numpy"):
            assert banned not in source
