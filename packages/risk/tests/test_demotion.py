"""Feature 326: the signal demotion the supervisor persists when a promoted
signal's live information coefficient falls below 40 percent of its backtest one.

The suite is organised around the sentence's claims, because they are the
things that can silently stop being true:

* **Below 40 percent.**  The comparison is strictly ``<``: a ratio below the
  bound demotes, a ratio at the bound is held, a ratio above it is held.  This
  is pinned at the boundary rather than approximated: a ratio of exactly 0.4 is
  *at* the line, and the test that passes one asserts ``None`` and no row.  The
  40 percent is a constant of the module, not configuration, so the value layer
  is where the bound lives.
* **The ratio is handed over, never derived.**  The store takes the signal's
  identity and the retention ratio the forward member computed — nothing else —
  and judges the ratio against the bound.  The cross-member test proves the
  ratio travels through the forward member's public seam: a real second
  interpreter computes it and this feature judges it.
* **A demotion is persisted.**  Only a *demoting* ratio lands, one row per
  signal, and a demotion that could not be recorded is raised rather than
  shrugged past.  The retry law is the ``node_id`` primary key: the same signal
  demoted twice is one row, and a second demotion re-reads the standing one
  with ``changed=False``.
* **The moment and the row are one fact.**  ``demoted_at`` is read back from
  the standing row rather than stamped into the value, so a re-filed demotion
  returns the first demotion's moment.

The refusals are the fifth subject: a node that is not a signal identity, a
ratio that is not a number, a bound that is not a band, a stored row no
demotion can be reconstructed as (including past a ``PRAGMA
ignore_check_constraints`` edit, which is why the value layer is the law and
the ``CHECK`` is only the belt), and a module-level demote that names no store.
Each in its own class, each named by the grep token its messages open with.
"""

from __future__ import annotations

import dataclasses
import os
import sqlite3
import subprocess
import sys
from contextlib import closing
from dataclasses import FrozenInstanceError
from datetime import UTC, datetime
from pathlib import Path

import pytest
from risk._identity import process_identity
from risk.demotion import (
    DATABASE_URL_ENV,
    DEMOTION_BOUND,
    RISK_SIGNAL_DEMOTION_TABLE,
    RiskSignalDemotionStore,
    SignalDemotion,
    demote_on_ic_drop,
    recorded_demotions,
)
from risk.errors import (
    SIGNAL_DEMOTION_CODE,
    RiskError,
    RiskSignalDemotionError,
    RiskStoreError,
)

REPO_ROOT = Path(__file__).resolve().parents[3]

#: A node that is a signal identity — a UUID — so the store's node validation
#: passes and the tests exercise the ratio-against-bound comparison.
NODE = "11111111-1111-1111-1111-111111111111"
#: A node that is not a UUID at all — the malformed-ask refusal.
NOT_A_NODE = "not-a-signal-identity"

#: A ratio below the bound (a demotion), at the bound (held), and above it
#: (held).  The 0.4 is pinned exactly, not approximated.
BELOW_BOUND = 0.2
AT_BOUND = 0.4
ABOVE_BOUND = 0.6


@pytest.fixture
def store(test_database_url: str) -> RiskSignalDemotionStore:
    return RiskSignalDemotionStore(test_database_url)


def _iso(moment: datetime) -> str:
    """The store's own canonical spelling, for asserting on stored strings.

    Restated rather than imported from the module's private helper, so these
    tests measure the stored spelling rather than a copy of the function that
    writes it: if the canonical form changed, a test that imported it would
    change with it and assert nothing.
    """
    return moment.astimezone(UTC).isoformat()


def _without_changed(record: SignalDemotion) -> SignalDemotion:
    """The record with the call's own ``changed`` bit dropped.

    ``changed`` answers whether *this* call wrote the row — a fact about the
    call, not the demotion.  The write path returns it ``True`` and every
    read-back returns it ``False``, so a record an operator reconciles against
    and the row the table holds cannot be compared raw.  The five facts that
    are columns of the row are what the write path and the read path must
    agree on, and this helper is what lets a test measure that agreement
    without the call's own answer in the way.
    """
    return dataclasses.replace(record, changed=False)


def _row_count(database_url: str) -> int:
    """How many rows the table holds, read with the driver directly."""
    path = database_url.removeprefix("sqlite:///")
    try:
        with closing(sqlite3.connect(path)) as connection:
            (count,) = connection.execute(
                f"SELECT COUNT(*) FROM {RISK_SIGNAL_DEMOTION_TABLE}"
            ).fetchone()
    except sqlite3.OperationalError:
        return 0
    return count


def _rows(database_url: str) -> list[tuple]:
    """Every raw row, so a test can assert on what is actually stored."""
    path = database_url.removeprefix("sqlite:///")
    try:
        with closing(sqlite3.connect(path)) as connection:
            return connection.execute(
                f"SELECT node_id, retention_ratio, demotion_bound, demoted_at, "
                f"supervisor_process_id FROM {RISK_SIGNAL_DEMOTION_TABLE} "
                f"ORDER BY node_id"
            ).fetchall()
    except sqlite3.OperationalError:
        return []


def _edit(
    database_url: str, statement: str, parameters: tuple = (), *, checks: bool = True
) -> None:
    """Rewrite the table with the driver directly — the tamper path.

    ``checks=False`` turns the schema's ``CHECK``\\ s off for the edit, which
    is what an out-of-band tool (or anyone who knows the pragma) can do.  The
    tests that use it are asserting the *value* layer refuses the row anyway —
    the reason this module treats the ``CHECK`` as belt rather than law.
    """
    path = database_url.removeprefix("sqlite:///")
    with closing(sqlite3.connect(path)) as connection, connection:
        if not checks:
            connection.execute("PRAGMA ignore_check_constraints = ON")
        connection.execute(statement, parameters)


# -- Below 40 percent -------------------------------------------------------------


class TestTheThresholdBoundary:
    def test_a_ratio_below_the_bound_demotes(
        self, store: RiskSignalDemotionStore, test_database_url: str
    ) -> None:
        # The comparison is strictly `<`, so a ratio below the bound is a
        # demotion: one row, changed, carrying the ratio and the bound.
        record = store.record_demotion(NODE, ratio=BELOW_BOUND)
        assert record is not None
        assert record.changed is True
        assert record.ratio == BELOW_BOUND
        assert record.bound == DEMOTION_BOUND
        assert _row_count(test_database_url) == 1

    def test_a_ratio_exactly_at_the_bound_is_held(
        self, store: RiskSignalDemotionStore, test_database_url: str
    ) -> None:
        # The boundary pinned exactly, not approximated: `<` excludes
        # equality, which is the convention feature 314's strict `<` and
        # feature 312's neighbour rule all state.  A ratio of exactly 0.4 is
        # *at* the line, so the signal is held — no row, no store opened.
        assert store.record_demotion(NODE, ratio=AT_BOUND) is None
        assert _row_count(test_database_url) == 0

    def test_a_ratio_above_the_bound_is_held(
        self, store: RiskSignalDemotionStore, test_database_url: str
    ) -> None:
        # A signal that kept more of its edge than the line demands is not a
        # demotion candidate.
        assert store.record_demotion(NODE, ratio=ABOVE_BOUND) is None
        assert _row_count(test_database_url) == 0

    def test_a_ratio_just_below_the_bound_demotes(
        self, store: RiskSignalDemotionStore
    ) -> None:
        # One unit in the last place below the bound is enough: the boundary
        # is a strict comparison, not a tolerance.
        record = store.record_demotion(NODE, ratio=DEMOTION_BOUND - 1e-9)
        assert record is not None
        assert record.ratio < DEMOTION_BOUND

    @pytest.mark.parametrize("bound", [0, -1, -0.5])
    def test_a_bound_that_is_not_a_band_is_refused(
        self, store: RiskSignalDemotionStore, bound: float
    ) -> None:
        # Every ratio other than exactly zero falls below a non-positive
        # bound, so a bound of zero or less is a supervisor that demotes on
        # every signal rather than on a fallen one.
        with pytest.raises(RiskSignalDemotionError) as refused:
            store.record_demotion(NODE, ratio=BELOW_BOUND, bound=bound)
        assert SIGNAL_DEMOTION_CODE in str(refused.value)
        assert "greater than zero" in str(refused.value)

    @pytest.mark.parametrize("bound", [True, False])
    def test_a_bool_bound_is_refused_by_name(
        self, store: RiskSignalDemotionStore, bound: bool
    ) -> None:
        # `isinstance(True, int)` is true in Python, so a naive numeric check
        # would accept `bound=True` and demote on a band of one — the reason
        # ops.live_metrics refuses bools before it looks at the number.
        with pytest.raises(RiskSignalDemotionError) as refused:
            store.record_demotion(NODE, ratio=BELOW_BOUND, bound=bound)
        assert SIGNAL_DEMOTION_CODE in str(refused.value)
        assert "bool" in str(refused.value)

    @pytest.mark.parametrize("bound", [float("nan"), float("inf"), float("-inf")])
    def test_a_non_finite_bound_is_refused(
        self, store: RiskSignalDemotionStore, bound: float
    ) -> None:
        # `nan` compares false against everything, so a `nan` bound would make
        # the comparison answer "held" for a ratio of any size — the one
        # direction this feature must never fail in.
        with pytest.raises(RiskSignalDemotionError) as refused:
            store.record_demotion(NODE, ratio=BELOW_BOUND, bound=bound)
        assert SIGNAL_DEMOTION_CODE in str(refused.value)
        assert "finite" in str(refused.value)

    def test_the_bound_has_a_default_and_it_is_40_percent(
        self, store: RiskSignalDemotionStore
    ) -> None:
        # The spec names "40 percent" and names no knob to retune it, so the
        # bound is a constant of the module, not configuration: a caller that
        # states no bound is judged against exactly 0.4.
        record = store.record_demotion(NODE, ratio=BELOW_BOUND)
        assert record is not None
        assert record.bound == 0.4 == DEMOTION_BOUND


class TestTheValueLayerIsTheLaw:
    """The CHECK is the belt; the value layer re-derives the comparison."""

    def _seed(self, database_url: str) -> None:
        """One well-formed demotion, then hand back for tampering."""
        RiskSignalDemotionStore(database_url).ensure_schema()
        _edit(
            database_url,
            f"INSERT INTO {RISK_SIGNAL_DEMOTION_TABLE} (node_id, "
            "retention_ratio, demotion_bound, demoted_at, supervisor_process_id) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                NODE,
                0.2,
                0.4,
                _iso(datetime(2026, 9, 25, 12, 0, 0, tzinfo=UTC)),
                "host/1",
            ),
        )

    def test_the_seed_is_well_formed(self, test_database_url: str) -> None:
        # The control: the row this class tampers with reads back cleanly
        # before it is edited, so every refusal below is the tamper's and not
        # the seed's.
        self._seed(test_database_url)
        (record,) = RiskSignalDemotionStore(test_database_url).demotions()
        assert record.ratio == 0.2

    def test_a_ratio_not_below_its_bound_is_refused(
        self, test_database_url: str
    ) -> None:
        # A signal at or above the bound is held, not demoted, and a row filed
        # for one reports a demotion that never fired.  The edit leaves the
        # arithmetic self-consistent — only the comparison is wrong — so this
        # is the judgement the value layer makes.
        self._seed(test_database_url)
        _edit(
            test_database_url,
            f"UPDATE {RISK_SIGNAL_DEMOTION_TABLE} SET retention_ratio = 0.5, "
            "demotion_bound = 0.4",
            checks=False,
        )
        with pytest.raises(RiskSignalDemotionError) as refused:
            RiskSignalDemotionStore(test_database_url).demotions()
        assert "is not below its bound" in str(refused.value)

    def test_a_bound_that_is_not_a_band_is_refused(
        self, test_database_url: str
    ) -> None:
        # A band of zero or less demotes on every signal; the value layer
        # refuses it even past a `PRAGMA ignore_check_constraints` edit.
        self._seed(test_database_url)
        _edit(
            test_database_url,
            f"UPDATE {RISK_SIGNAL_DEMOTION_TABLE} SET demotion_bound = 0",
            checks=False,
        )
        with pytest.raises(RiskSignalDemotionError) as refused:
            RiskSignalDemotionStore(test_database_url).demotions()
        assert SIGNAL_DEMOTION_CODE in str(refused.value)

    @pytest.mark.parametrize("column", ["retention_ratio", "demotion_bound"])
    def test_a_non_numeric_value_is_refused(
        self, test_database_url: str, column: str
    ) -> None:
        # A numeric string is coerced by the column's REAL affinity, so the
        # tamper has to be one affinity cannot rescue: a word.  SQLite stores
        # it as-is (TEXT in a REAL column), and the value layer is what
        # refuses it.
        self._seed(test_database_url)
        _edit(
            test_database_url,
            f"UPDATE {RISK_SIGNAL_DEMOTION_TABLE} SET {column} = 'three'",
            checks=False,
        )
        with pytest.raises(RiskSignalDemotionError) as refused:
            RiskSignalDemotionStore(test_database_url).demotions()
        assert SIGNAL_DEMOTION_CODE in str(refused.value)

    def test_a_row_with_no_recording_process_is_refused(
        self, test_database_url: str
    ) -> None:
        # A demotion nobody can attribute is the one thing this record cannot
        # leave an operator to guess at.
        self._seed(test_database_url)
        _edit(
            test_database_url,
            f"UPDATE {RISK_SIGNAL_DEMOTION_TABLE} SET supervisor_process_id = '  '",
        )
        with pytest.raises(RiskSignalDemotionError) as refused:
            RiskSignalDemotionStore(test_database_url).demotions()
        assert SIGNAL_DEMOTION_CODE in str(refused.value)

    def test_a_row_with_no_recording_instant_is_refused(
        self, test_database_url: str
    ) -> None:
        # A demotion must say unambiguously when the signal lost its
        # promotion, or the record cannot be ordered against anything.
        self._seed(test_database_url)
        _edit(
            test_database_url,
            f"UPDATE {RISK_SIGNAL_DEMOTION_TABLE} SET demoted_at = 'whenever'",
        )
        with pytest.raises(RiskSignalDemotionError) as refused:
            RiskSignalDemotionStore(test_database_url).demotions()
        assert SIGNAL_DEMOTION_CODE in str(refused.value)
        assert "whenever" in str(refused.value)


# -- The ratio is handed over -----------------------------------------------------


class TestTheRatioIsHandedOver:
    def test_the_store_takes_the_ratio_not_the_coefficients(
        self, store: RiskSignalDemotionStore
    ) -> None:
        # The store's record takes the node and the ratio — nothing else.  It
        # does not name the forward member's columns and does not reach into
        # its tables: a member never imports a sibling's tables.
        import inspect

        signature = inspect.signature(store.record_demotion)
        parameters = set(signature.parameters)
        assert "node_id" in parameters
        assert "ratio" in parameters
        assert "live_ic" not in parameters
        assert "backtest_ic" not in parameters

    def test_the_module_never_names_the_forward_columns(self) -> None:
        # The demotion reaches the ratio through the forward member's public
        # seam, never reading forward_record itself.  The module's source names
        # no forward column.
        source = Path(__file__).resolve().parents[1] / "src" / "risk" / "demotion.py"
        text = source.read_text()
        assert "live_ic" not in text
        assert "backtest_ic" not in text
        assert "forward_record" not in text

    def test_a_real_second_interpreter_computes_the_ratio_this_feature_judges(
        self, tmp_path: Path
    ) -> None:
        # The ratio travels through the forward member's public seam: a real
        # second interpreter computes it and this feature judges it.  The
        # database, not any process's memory, is the coordination point.  The
        # seed drives the *real* promotion member (to pre-register and decide
        # the signal) and the *real* forward member (to open the record, append
        # the live IC observations, and land the backtest coefficient) — the
        # same chain a production supervisor speaks to, so the ratio this
        # feature is handed is the one those members actually computed.
        database = tmp_path / "cross-member.db"
        url = f"sqlite:///{database}"
        node = "11111111-1111-4111-8111-111111111111"
        seed = f"""
import sys
import datetime as dt

from promotion import PreRegistrations, PromotionCriteria
from promotion.decision import PromotionDecisions
from forward.record import ForwardRecords
from forward.observation import ForwardObservations
from forward.retention import ForwardIcRetentions

url = sys.argv[1]
node = {node!r}

# The discovery loop's writes: the node row, the sealed epoch, the promotion.
registrations = PreRegistrations(url)
registrations._connect().close()
connection = registrations._connect()
with connection:
    connection.execute(
        "INSERT INTO node (id, campaign_id, theme_root, depth) VALUES (?, ?, ?, ?)",
        (node, "22222222-2222-4222-8222-222222222222", "macro", 1),
    )
    connection.execute(
        "INSERT INTO epoch_ledger (epoch_id, sealed_at) VALUES (?, ?)",
        ("epoch-2026-01", "2026-01-01T00:00:00+00:00"),
    )
connection.close()
registrations.pre_register(
    node,
    "epoch-2026-01",
    PromotionCriteria(
        theta=0.3, alpha=0.05, max_fdr_deploy=0.25,
        min_worlds=50, min_coverage_strata=3, min_forward_days=90,
    ),
    clock=lambda: dt.datetime.fromisoformat("2026-02-01T00:00:00+00:00"),
)
PromotionDecisions(url).record_decision(
    node, decided_at=dt.datetime.fromisoformat("2026-03-01T12:00:00+00:00")
)

# Feature 332 opens the record; feature 333 appends the live IC observations;
# feature 337 lands the backtest coefficient.  Two days at a live IC of 0.1
# against a backtest of 0.5 give a retention ratio of 0.2.
records = ForwardRecords(url)
records.open_record(node, forward_days=90)
observations = ForwardObservations.over(records)
observations.append_observation(
    node, observed_on=dt.date(2026, 3, 2), live_ic=0.1, forward_days=90
)
observations.append_observation(
    node, observed_on=dt.date(2026, 3, 3), live_ic=0.1, forward_days=90
)
retentions = ForwardIcRetentions.over(records)
retentions.record_backtest_ic(node, backtest_ic=0.5)
"""
        env = {
            **os.environ,
            # Every declared member's scan root on the path, exactly as the
            # production loader and the member suites' conftests do — the
            # promotion member is a real dependency of this seed, and a
            # hard-coded single path could quietly disagree with the
            # declaration that decides which members are reachable.
            "PYTHONPATH": os.pathsep.join(
                [
                    str(REPO_ROOT / "src"),
                    *(
                        str(p) for p in sorted((REPO_ROOT / "packages").glob("*/src"))
                    ),
                    os.environ.get("PYTHONPATH", ""),
                ]
            ),
        }
        result = subprocess.run(
            [sys.executable, "-c", seed, url],
            cwd=str(REPO_ROOT),
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr
        # This process reads the ratio the forward member computed — through
        # the forward member's own public seam — and judges it.
        from forward.retention import forward_ic_retention

        retention = forward_ic_retention(node, database_url=url)
        assert retention.node_id == node
        assert retention.ratio == pytest.approx(0.1 / 0.5)
        # And that ratio, handed over, is below the bound, so it demotes.
        record = demote_on_ic_drop(
            retention.node_id, ratio=retention.ratio, database_url=url
        )
        assert record is not None
        assert record.ratio == pytest.approx(0.2)
        assert record.changed is True


# -- A demotion is persisted ------------------------------------------------------


class TestTheRecording:
    def test_every_column_lands_with_its_own_value(
        self, store: RiskSignalDemotionStore, test_database_url: str
    ) -> None:
        record = store.record_demotion(NODE, ratio=BELOW_BOUND)
        assert record is not None
        (node_id, ratio, bound, demoted_at, sender) = _rows(test_database_url)[0]
        assert node_id == record.node_id == NODE
        assert ratio == BELOW_BOUND
        assert bound == DEMOTION_BOUND
        assert demoted_at == _iso(record.demoted_at)
        assert sender == process_identity()

    def test_a_ratio_at_or_above_the_bound_opens_nothing(
        self, store: RiskSignalDemotionStore, test_database_url: str
    ) -> None:
        # A table of every judgement is a table whose demotions an operator has
        # to pick out first, so a ratio at or above the bound writes nothing
        # and does not so much as open the store.
        assert store.record_demotion(NODE, ratio=AT_BOUND) is None
        assert store.record_demotion(NODE, ratio=ABOVE_BOUND) is None
        assert _row_count(test_database_url) == 0

    def test_the_record_names_the_process_that_recorded_it(
        self, store: RiskSignalDemotionStore
    ) -> None:
        # Read from the kernel rather than accepted from the caller, the same
        # label and for the same reason the kill channel's send refuses a
        # caller-supplied one.
        record = store.record_demotion(NODE, ratio=BELOW_BOUND)
        assert record is not None
        assert record.supervisor_process_id == process_identity()
        assert record.supervisor_process_id == store.process_id

    def test_a_label_states_a_process_or_is_refused(
        self, store: RiskSignalDemotionStore
    ) -> None:
        # Keyword-only, so a caller on the supervisor's own path does not pass
        # it — and the one that does must say something.
        with pytest.raises(RiskSignalDemotionError) as refused:
            store.record_demotion(NODE, ratio=BELOW_BOUND, supervisor_process_id="   ")
        assert SIGNAL_DEMOTION_CODE in str(refused.value)

    def test_the_record_is_frozen(self, store: RiskSignalDemotionStore) -> None:
        record = store.record_demotion(NODE, ratio=BELOW_BOUND)
        assert record is not None
        with pytest.raises(FrozenInstanceError):
            record.ratio = 0.9  # type: ignore[misc]

    def test_a_demotion_that_could_not_be_written_is_raised_not_shrugged(
        self, store: RiskSignalDemotionStore, test_database_url: str, monkeypatch
    ) -> None:
        # The row is the record of why the signal was demoted; a demotion with
        # nothing on disk to account for it is indistinguishable from a signal
        # that was never judged.  The store's own *write* connection is what
        # fails here -- the one open that brings the schema up and lands the
        # row, so the patch fails that single open and the retry's open
        # succeeds.
        real_connect = RiskSignalDemotionStore._connect
        calls = {"n": 0}

        def fail_the_write(self):
            calls["n"] += 1
            if calls["n"] == 1:  # the write's single connection fails; the retry's succeeds
                raise sqlite3.OperationalError("disk I/O error")
            return real_connect(self)

        monkeypatch.setattr(RiskSignalDemotionStore, "_connect", fail_the_write)
        with pytest.raises(RiskStoreError) as refused:
            store.record_demotion(NODE, ratio=BELOW_BOUND)
        assert "could not record" in str(refused.value)
        monkeypatch.undo()
        retried = store.record_demotion(NODE, ratio=BELOW_BOUND)
        assert retried is not None
        assert _row_count(test_database_url) == 1

    def test_a_refused_insert_is_this_features_own_refusal(
        self, store: RiskSignalDemotionStore, test_database_url: str
    ) -> None:
        # A tampered table can grow a constraint this store's own insert then
        # trips — and a *bare* IntegrityError leaking out of a demotion would
        # send an operator to the driver for a fault whose noun is the
        # measurement.
        store.ensure_schema()
        _edit(
            test_database_url,
            f"CREATE TRIGGER refuse_demotion_rows BEFORE INSERT ON "
            f"{RISK_SIGNAL_DEMOTION_TABLE} BEGIN SELECT RAISE(ABORT, 'no'); END",
        )
        with pytest.raises(RiskSignalDemotionError) as refused:
            store.record_demotion(NODE, ratio=BELOW_BOUND)
        assert SIGNAL_DEMOTION_CODE in str(refused.value)


class TestTheRetryLaw:
    def test_the_same_signal_demoted_twice_is_one_row(
        self, store: RiskSignalDemotionStore, test_database_url: str
    ) -> None:
        # A supervisor restarting after a crash re-files the same signal — and
        # rewriting the moment the signal lost its promotion would be a second
        # demotion for one fault.  First-write-wins: the second filing re-reads
        # the standing demotion with changed=False.
        first = store.record_demotion(NODE, ratio=BELOW_BOUND)
        again = store.record_demotion(NODE, ratio=BELOW_BOUND - 0.1)
        assert first is not None and again is not None
        assert again.changed is False
        assert again.ratio == first.ratio
        assert again.demoted_at == first.demoted_at
        assert _row_count(test_database_url) == 1

    def test_a_second_signal_is_a_second_row(
        self, store: RiskSignalDemotionStore, test_database_url: str
    ) -> None:
        # Because it is a different signal.
        second = "22222222-2222-2222-2222-222222222222"
        store.record_demotion(NODE, ratio=BELOW_BOUND)
        store.record_demotion(second, ratio=BELOW_BOUND)
        assert _row_count(test_database_url) == 2

    def test_the_law_is_a_constraint_not_a_convention(
        self, store: RiskSignalDemotionStore, test_database_url: str
    ) -> None:
        # A raw insert of the same node — a second writer that knows nothing of
        # this module — is refused by the primary key, so the one-row-per-
        # signal law holds against anything that can reach the table.
        store.ensure_schema()
        _edit(
            test_database_url,
            f"INSERT INTO {RISK_SIGNAL_DEMOTION_TABLE} (node_id, "
            "retention_ratio, demotion_bound, demoted_at, supervisor_process_id) "
            "VALUES (?, ?, ?, ?, ?)",
            (NODE, 0.2, 0.4, _iso(datetime(2026, 9, 25, tzinfo=UTC)), "host/1"),
        )
        with pytest.raises(sqlite3.IntegrityError):
            _edit(
                test_database_url,
                f"INSERT INTO {RISK_SIGNAL_DEMOTION_TABLE} (node_id, "
                "retention_ratio, demotion_bound, demoted_at, "
                "supervisor_process_id) VALUES (?, ?, ?, ?, ?)",
                (NODE, 0.2, 0.4, _iso(datetime(2026, 9, 25, tzinfo=UTC)), "host/2"),
            )

    def test_a_raced_insert_re_reads_the_winners_row(
        self, store: RiskSignalDemotionStore, test_database_url: str, monkeypatch
    ) -> None:
        # Another process records the same signal between this call's check and
        # its insert.  One signal is one demotion, so the other process's row
        # *is* this demotion's record: the loser re-reads it rather than
        # reporting a conflict where there is none.
        store.ensure_schema()
        _edit(
            test_database_url,
            f"INSERT INTO {RISK_SIGNAL_DEMOTION_TABLE} (node_id, "
            "retention_ratio, demotion_bound, demoted_at, supervisor_process_id) "
            "VALUES (?, ?, ?, ?, ?)",
            (NODE, 0.2, 0.4, _iso(datetime(2026, 9, 25, tzinfo=UTC)), "other/host"),
        )
        real_row_for = RiskSignalDemotionStore._row_for

        def raced(self, connection, node):
            return None if connection is None else real_row_for(self, connection, node)

        # Simulate the race's interleaving: the check sees nothing, so the
        # insert then hits the primary key, exactly as it would if the other
        # writer had committed a moment earlier.
        monkeypatch.setattr(RiskSignalDemotionStore, "_row_for", raced)
        record = store.record_demotion(NODE, ratio=BELOW_BOUND)
        assert record is not None
        assert record.supervisor_process_id == "other/host"
        assert record.changed is False
        assert _row_count(test_database_url) == 1


# -- The read ---------------------------------------------------------------------


class TestTheRead:
    def test_the_sweep_orders_by_signal_identity(
        self, store: RiskSignalDemotionStore
    ) -> None:
        # The sweep answers *which signals have been demoted*, so it is ordered
        # by the signal identity, deterministically.
        second = "22222222-2222-2222-2222-222222222222"
        store.record_demotion(second, ratio=BELOW_BOUND)
        store.record_demotion(NODE, ratio=BELOW_BOUND)
        demotions = store.demotions()
        assert [record.node_id for record in demotions] == [NODE, second]

    def test_an_empty_record_reads_as_an_empty_tuple(
        self, store: RiskSignalDemotionStore
    ) -> None:
        # A deployment whose signals are fine holds no rows, and the empty
        # answer is truthful rather than a clean bill of signal health.
        assert store.demotions() == ()

    def test_a_record_reads_back_as_the_value_that_was_written(
        self, store: RiskSignalDemotionStore
    ) -> None:
        # The write path and the read path are judged by one rule, so a record
        # an operator reconciles against and the row the table holds cannot be
        # two things that disagree.  The one fact that differs is ``changed``:
        # the write returns it ``True`` (this call wrote the row) and the read
        # returns it ``False`` (a read wrote nothing) — so it is dropped before
        # the two are compared, and what is compared is the demotion itself.
        written = store.record_demotion(NODE, ratio=BELOW_BOUND)
        (read,) = store.demotions()
        assert _without_changed(read) == _without_changed(written)

    def test_the_demotion_for_a_signal_is_its_standing_row(
        self, store: RiskSignalDemotionStore
    ) -> None:
        # The reader's primary question — *has this signal been demoted?*
        store.record_demotion(NODE, ratio=BELOW_BOUND)
        record = store.demotion_for(NODE)
        assert record is not None
        assert record.ratio == BELOW_BOUND
        assert record.changed is False

    def test_a_signal_that_was_not_demoted_reads_none(
        self, store: RiskSignalDemotionStore
    ) -> None:
        # A signal that holds its promotion has no standing demotion.
        assert store.demotion_for(NODE) is None

    def test_the_read_refuses_a_row_no_demotion_can_be(
        self, store: RiskSignalDemotionStore, test_database_url: str
    ) -> None:
        # A skipped row is a demotion an operator would never learn about, so
        # the read refuses rather than skipping.
        store.record_demotion(NODE, ratio=BELOW_BOUND)
        _edit(
            test_database_url,
            f"UPDATE {RISK_SIGNAL_DEMOTION_TABLE} SET retention_ratio = 0.9, "
            "demotion_bound = 0.4",
            checks=False,
        )
        with pytest.raises(RiskSignalDemotionError) as refused:
            store.demotions()
        assert SIGNAL_DEMOTION_CODE in str(refused.value)


# -- The module-level spellings ---------------------------------------------------


class TestTheModuleLevelSpellings:
    def test_a_fired_ratio_records_through_the_named_store(
        self, test_database_url: str
    ) -> None:
        # The record the write returns and the row the reader sweeps are one
        # demotion.  ``changed`` differs — the write answers ``True`` (this
        # call wrote the row) and the read answers ``False`` (a read wrote
        # nothing) — so it is dropped before the two are compared, and what is
        # compared is the demotion itself, not the call that produced it.
        record = demote_on_ic_drop(NODE, ratio=BELOW_BOUND, database_url=test_database_url)
        assert record is not None
        (swept,) = recorded_demotions(database_url=test_database_url)
        assert _without_changed(swept) == _without_changed(record)

    def test_a_held_ratio_records_nothing(self, test_database_url: str) -> None:
        assert demote_on_ic_drop(NODE, ratio=AT_BOUND, database_url=test_database_url) is None
        assert recorded_demotions(database_url=test_database_url) == ()

    def test_the_environment_names_the_store_when_no_url_does(
        self, test_database_url: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(DATABASE_URL_ENV, test_database_url)
        record = demote_on_ic_drop(NODE, ratio=BELOW_BOUND)
        assert record is not None

    def test_an_explicit_url_wins_over_the_environment(
        self, test_database_url: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(DATABASE_URL_ENV, f"sqlite:///{tmp_path / 'ignored.db'}")
        record = demote_on_ic_drop(NODE, ratio=BELOW_BOUND, database_url=test_database_url)
        assert record is not None
        assert _row_count(test_database_url) == 1

    def test_a_held_ratio_needs_no_store(self) -> None:
        # Nothing was demoted, so there is nothing to account for: an
        # unconfigured deployment that merely judges is not an error.
        assert demote_on_ic_drop(NODE, ratio=AT_BOUND, env={}) is None

    def test_a_fired_ratio_with_no_store_is_refused_by_name(self) -> None:
        # From this moment the signal is demoted and nothing would record why:
        # the next cycle could not tell a demoted signal from one that was
        # never judged, which is the record this feature exists to keep.
        with pytest.raises(RiskSignalDemotionError) as refused:
            demote_on_ic_drop(NODE, ratio=BELOW_BOUND, env={})
        message = str(refused.value)
        assert message.startswith(SIGNAL_DEMOTION_CODE)
        assert DATABASE_URL_ENV in message

    def test_the_ratio_is_judged_before_the_store_is_demanded(self) -> None:
        # A held ratio never reaches the no-store refusal, deliberately: the
        # refusal is about a *fired* demotion, not a signal that was never
        # judged.
        assert demote_on_ic_drop(NODE, ratio=ABOVE_BOUND, env={}) is None

    def test_the_readers_absence_answers_the_empty_truth(self) -> None:
        # Recording refuses without a store, so a deployment that names none
        # holds no demotions to read, and the empty answer is truthful — kept
        # distinct because a caller that mistook an unconfigured deployment for
        # an empty record would read a table with no demotions in it and call
        # it a set of signals that never decayed.
        assert recorded_demotions(env={}) == ()

    def test_the_readers_absence_is_not_the_recorders_refusal(self) -> None:
        # The asymmetry, in one test: the same absent store refuses a demotion
        # and answers a read.
        with pytest.raises(RiskSignalDemotionError):
            demote_on_ic_drop(NODE, ratio=BELOW_BOUND, env={})
        assert recorded_demotions(env={}) == ()

    def test_the_read_sweeps_the_named_store(
        self, test_database_url: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(DATABASE_URL_ENV, test_database_url)
        demote_on_ic_drop(NODE, ratio=BELOW_BOUND)
        second = "22222222-2222-2222-2222-222222222222"
        demote_on_ic_drop(second, ratio=BELOW_BOUND)
        assert len(recorded_demotions()) == 2


# -- The refusals -----------------------------------------------------------------


class TestTheRefusals:
    def test_a_node_that_is_not_a_signal_identity_is_refused(
        self, store: RiskSignalDemotionStore
    ) -> None:
        # The demotion is about a signal, and a signal is the forward record's
        # node_id — a UUID.  A node_id that is not a UUID names no signal this
        # member can demote.
        with pytest.raises(RiskSignalDemotionError) as refused:
            store.record_demotion(NOT_A_NODE, ratio=BELOW_BOUND)
        assert SIGNAL_DEMOTION_CODE in str(refused.value)
        assert "signal identity" in str(refused.value)

    def test_a_ratio_that_is_not_a_number_is_refused(
        self, store: RiskSignalDemotionStore
    ) -> None:
        # The ratio is the live IC divided by the backtest IC, and it is the
        # figure the demotion line acts on, so a ratio that is not one number
        # leaves the comparison with no operand.
        with pytest.raises(RiskSignalDemotionError) as refused:
            store.record_demotion(NODE, ratio="below")  # type: ignore[arg-type]
        assert SIGNAL_DEMOTION_CODE in str(refused.value)

    @pytest.mark.parametrize("ratio", [True, False])
    def test_a_bool_ratio_is_refused_by_name(
        self, store: RiskSignalDemotionStore, ratio: bool
    ) -> None:
        # `isinstance(True, int)` is true in Python, so a naive numeric check
        # would accept `ratio=True` and demote on a band of one.
        with pytest.raises(RiskSignalDemotionError) as refused:
            store.record_demotion(NODE, ratio=ratio)
        assert SIGNAL_DEMOTION_CODE in str(refused.value)
        assert "bool" in str(refused.value)

    @pytest.mark.parametrize("ratio", [float("nan"), float("inf"), float("-inf")])
    def test_a_non_finite_ratio_is_refused(
        self, store: RiskSignalDemotionStore, ratio: float
    ) -> None:
        # `nan` compares false against everything, so a `nan` ratio would never
        # fall below the bound and a demoted signal would read as though it
        # were fine — the one direction this feature must never fail in.
        with pytest.raises(RiskSignalDemotionError) as refused:
            store.record_demotion(NODE, ratio=ratio)
        assert SIGNAL_DEMOTION_CODE in str(refused.value)
        assert "finite" in str(refused.value)

    def test_a_refusal_is_the_members_own_class(self) -> None:
        # Every face of feature 326 is catchable by the base class, so a
        # supervisor wrapping its whole demotion path catches them all.
        with pytest.raises(RiskError):
            RiskSignalDemotionStore("sqlite:///tmp.db").record_demotion(
                NOT_A_NODE, ratio=BELOW_BOUND
            )

    def test_a_refused_node_writes_nothing(
        self, store: RiskSignalDemotionStore, test_database_url: str
    ) -> None:
        # A malformed ask is refused before anything is opened, so a refused
        # call leaves no row and no file behind.
        with pytest.raises(RiskSignalDemotionError):
            store.record_demotion(NOT_A_NODE, ratio=BELOW_BOUND)
        assert _row_count(test_database_url) == 0


# -- The store construction -------------------------------------------------------


class TestTheStoreConstruction:
    def test_an_empty_url_is_refused(self) -> None:
        with pytest.raises(RiskStoreError):
            RiskSignalDemotionStore("   ")

    def test_a_non_sqlite_url_is_an_address_fault_by_name(self) -> None:
        # Not this feature's own class: an address this member cannot speak has
        # an address repair, and a caller sent from a malformed ratio to a bad
        # URL would edit the wrong file.
        store = RiskSignalDemotionStore("postgresql://host/db")
        with pytest.raises(RiskStoreError) as refused:
            store.ensure_schema()
        assert "postgresql" in str(refused.value)

    def test_an_in_memory_url_is_refused(self) -> None:
        # A demotion that vanished would leave a demotion this feature exists
        # to account for with nothing on disk to account for it.
        with pytest.raises(RiskStoreError):
            RiskSignalDemotionStore("sqlite:///:memory:").ensure_schema()

    def test_resolve_names_the_store_or_none(self, test_database_url: str) -> None:
        assert RiskSignalDemotionStore.resolve(env={}) is None
        assert RiskSignalDemotionStore.resolve(env={DATABASE_URL_ENV: "  "}) is None
        resolved = RiskSignalDemotionStore.resolve(
            env={DATABASE_URL_ENV: test_database_url}
        )
        assert resolved is not None
        assert resolved.database_url == test_database_url

    def test_construction_opens_nothing(self, tmp_path: Path) -> None:
        # Composing an application never touches the database, and a store
        # costs nothing until a demotion is recorded or the table is read.
        database = tmp_path / "untouched.db"
        RiskSignalDemotionStore(f"sqlite:///{database}")
        assert not database.exists()

    def test_the_path_is_the_file_the_url_names(self, test_database_url: str) -> None:
        assert RiskSignalDemotionStore(test_database_url).path == Path(
            test_database_url.removeprefix("sqlite:///")
        )


# -- Two processes ----------------------------------------------------------------


class TestAcrossProcesses:
    def test_a_demotion_another_supervisor_judged_is_one_this_process_reads(
        self, tmp_path: Path
    ) -> None:
        # The database, not any process's memory, is the coordination point —
        # and §17 leaves no port to serve a socket on.  The supervisor is an
        # actual second interpreter.
        database = tmp_path / "cross-process.db"
        url = f"sqlite:///{database}"
        script = (
            "import sys;"
            "from risk.demotion import RiskSignalDemotionStore;"
            "from risk._identity import process_identity;"
            "record = RiskSignalDemotionStore(sys.argv[1]).record_demotion("
            "'11111111-1111-1111-1111-111111111111', ratio=0.2);"
            "print(record.ratio, record.changed,"
            " record.supervisor_process_id == process_identity(),"
            " process_identity())"
        )
        env = {
            **os.environ,
            "PYTHONPATH": os.pathsep.join(
                [
                    str(REPO_ROOT / "src"),
                    str(REPO_ROOT / "packages" / "risk" / "src"),
                    os.environ.get("PYTHONPATH", ""),
                ]
            ),
        }
        result = subprocess.run(
            [sys.executable, "-c", script, url],
            cwd=str(REPO_ROOT),
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr
        ratio, changed, same_process, theirs = result.stdout.strip().split(" ", 3)
        assert ratio == "0.2" and changed == "True" and same_process == "True"

        (record,) = RiskSignalDemotionStore(url).demotions()
        assert record.ratio == 0.2
        assert record.supervisor_process_id == theirs
        assert record.supervisor_process_id != process_identity()

    def test_this_process_records_after_theirs_without_colliding(
        self, tmp_path: Path
    ) -> None:
        # A different signal is a different demotion, so the second process
        # appends rather than re-reading the first's row.
        database = tmp_path / "two-supervisors.db"
        url = f"sqlite:///{database}"
        script = (
            "import sys;"
            "from risk.demotion import RiskSignalDemotionStore;"
            "RiskSignalDemotionStore(sys.argv[1]).record_demotion("
            "'11111111-1111-1111-1111-111111111111', ratio=0.2)"
        )
        env = {
            **os.environ,
            "PYTHONPATH": os.pathsep.join(
                [
                    str(REPO_ROOT / "src"),
                    str(REPO_ROOT / "packages" / "risk" / "src"),
                    os.environ.get("PYTHONPATH", ""),
                ]
            ),
        }
        result = subprocess.run(
            [sys.executable, "-c", script, url],
            cwd=str(REPO_ROOT),
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr
        second = "22222222-2222-2222-2222-222222222222"
        ours = RiskSignalDemotionStore(url).record_demotion(second, ratio=0.2)
        assert ours is not None and ours.changed is True
        assert _row_count(url) == 2
