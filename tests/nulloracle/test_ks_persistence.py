"""Feature 123, end to end: the assembled system persists the KS p-value.

app_spec.xml, "Null Oracle & Planted Nulls", feature 123: *System persists
the p-value of a two-sample Kolmogorov-Smirnov test comparing in-sample
scores of null nodes against real nodes per campaign.*

The member's own suite (``packages/nulloracle/tests``) pins each contract in
isolation — the statistic, its two estimators, the refusals, the store, the
read-back, the component.  This suite pins the sentence those contracts are *for*,
through the assembled system: the guard composed by the application factory,
read through ``create_app().get``, writing the campaign row that
``migrations/versions/0111_campaign_table.py`` created for it.

That distinction is the whole point here.  §7.4's p-value is the one number
that can void a campaign, halt dreaming and remove it from the replay pool
(feature 124 decides that; this one measures it), and it is written onto a
table the *orchestrator* created rather than one this member owns.  So the
integration question is not "does the arithmetic work" but:

* does the composed system carry the guard at all, in a deployment whose
  ``DATABASE_URL`` the root conftest supplies;
* does its number land on ``campaign.ks_pvalue`` — the column the migration
  named for this feature — on a campaign row the orchestrator wrote, with the
  planning-time columns untouched;
* does the campaign come out **still calibrated**, because the verdict is
  feature 124's and a guard that also decided would be a threshold nobody
  could audit;
* and does the assembled system's `POST /target`-shaped read path — the
  composed component — hand a caller the same reading the store holds.

A member that passed its unit suite while the composed application carried no
guard at all would satisfy every requirement of the arithmetic tests and none
of these.
"""

from __future__ import annotations

import uuid

import pytest
from nulloracle import DATABASE_URL_ENV

from app.module_loader import create_app

KS_GUARD_COMPONENT_NAME = "nulloracle-ks-guard"
CAMPAIGN_TABLE = "campaign"


def campaign_row(**overrides) -> tuple:
    """A campaign's planning-time columns, as the migration spells them.

    The three ``NOT NULL`` columns with no default — the type, ``W`` and
    ``φ`` — in the shape ``0111_campaign_table.py`` describes a campaign as
    being planned with.  A campaign is written by its planner *before any
    node is expanded*, which is why this suite inserts the row itself rather
    than expecting the guard to: the guard measures a campaign, it does not
    invent one.
    """
    fields = {"campaign_type": "Type-R", "workspace_count": 12, "null_fraction": 0.1667}
    fields.update(overrides)
    return tuple(fields.values())


@pytest.fixture
def composed_guard():
    """The guard the *composed application* carries for this environment.

    Read out of the application the factory builds — not constructed
    directly — because the claim under test is about the assembled system: a
    deployment sets ``DATABASE_URL`` and the composed application must carry
    a usable guard journal pointed at it.  The root conftest points that
    variable at a per-test SQLite file, so every test here is isolated.
    """
    return create_app().get(KS_GUARD_COMPONENT_NAME)


@pytest.fixture
def planned_campaign(composed_guard):
    """A campaign the orchestrator has planned, and its id.

    Inserted through the guard's own connection so the row lands in the same
    database the guard writes to, using the same table — which is the
    point: one table, the orchestrator's, with the guard filling one column
    of it.
    """
    identifier = str(uuid.uuid4())
    with composed_guard._connect() as connection:
        connection.execute(
            f"INSERT INTO {CAMPAIGN_TABLE} (id, campaign_type, workspace_count, "
            "null_fraction) VALUES (?, ?, ?, ?)",
            (identifier, *campaign_row()),
        )
    return identifier


def samples(count: int, *, gap: float = 50.0):
    """Two disjoint score samples: ``count`` null nodes and ``count`` real.

    Keyed by node id rather than handed over as bare scores, because that is
    the form a campaign holds and the form that gets the disjointness check —
    §7.1's sidecar keys one bit per node, so the partition is what the
    samples are *of*.
    """
    nodes = [str(uuid.uuid4()) for _ in range(count * 2)]
    null = {node: index * 0.01 for index, node in enumerate(nodes[:count])}
    real = {node: index * 0.01 + gap for index, node in enumerate(nodes[count:])}
    return null, real


class TestTheComposedSystemCarriesTheGuard:
    def test_the_factory_composes_a_guard_for_the_environment(
        self, composed_guard, test_database_url: str
    ) -> None:
        assert composed_guard is not None
        assert composed_guard.database_url == test_database_url

    def test_a_fresh_composition_reaches_the_same_store(
        self, composed_guard, test_database_url: str
    ) -> None:
        # ``create_app().get`` is how the rest of this category's features
        # reach the reading, so it must resolve to the store the factory
        # composed.
        assert create_app().get(KS_GUARD_COMPONENT_NAME).database_url == composed_guard.database_url

    def test_both_of_the_members_components_compose_together(
        self, sidecar_path, key_ref: str, composed_guard
    ) -> None:
        # §7.4's guard needs the labels (from the sidecar's file) and the
        # campaign (from the relational store). A deployment configured for
        # both gets both, which is what makes the guard job runnable at all.
        assert create_app().get("nulloracle") is not None
        assert composed_guard is not None

    def test_an_unconfigured_deployment_composes_no_guard(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Degrade, don't break: an absent relational store is a discoverable
        # state, and this member's unset variable must not take composition
        # down for every other feature in the workspace.
        monkeypatch.delenv(DATABASE_URL_ENV, raising=False)
        app = create_app()
        assert app.get(KS_GUARD_COMPONENT_NAME) is None
        assert len(app.order) > 5  # ...and the rest of the workspace is there

    def test_composing_the_guard_creates_no_database_file(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path
    ) -> None:
        # Construction resolves nothing: the factory builds every registered
        # component on every create_app(), and a store that opened a
        # connection at construction would create — and lock — a file in the
        # path of every process that merely composed the app.
        path = tmp_path / "never-created.db"
        monkeypatch.setenv(DATABASE_URL_ENV, f"sqlite:///{path}")
        app = create_app()
        assert app.get(KS_GUARD_COMPONENT_NAME) is not None
        assert not path.exists()


class TestThePValueIsPersistedThroughTheAssembledSystem:
    def test_a_campaigns_pvalue_lands_on_the_migration_s_own_column(
        self, composed_guard, planned_campaign
    ) -> None:
        # The headline claim of feature 123, end to end: the number the guard
        # computed is on ``campaign.ks_pvalue`` — the column
        # ``0111_campaign_table.py`` created for it and stated the guard would
        # fill. Feature 124's verdict reads it there; the dashboard's
        # instrument status reads it there.
        null, real = samples(40)
        record = composed_guard.guard(planned_campaign, null, real)
        assert 0.0 <= record.pvalue <= 1.0
        with composed_guard._connect() as connection:
            row = connection.execute(
                "SELECT ks_pvalue FROM campaign WHERE id = ?", (planned_campaign,)
            ).fetchone()
        assert row[0] == record.pvalue

    def test_the_read_path_returns_the_reading_the_write_path_wrote(
        self, composed_guard, planned_campaign
    ) -> None:
        null, real = samples(30)
        written = composed_guard.guard(planned_campaign, null, real)
        loaded = composed_guard.load(planned_campaign)
        assert loaded == written
        assert loaded.null_count == 30 and loaded.real_count == 30

    def test_the_provenance_beside_the_number_is_persisted(
        self, composed_guard, planned_campaign
    ) -> None:
        # A bare REAL on the campaign row is a number nobody can check:
        # 0.31 from 400 nodes and 0.31 from four are the same value and
        # opposite findings. The guard's own row carries what makes the
        # stored p-value interpretable.
        null, real = samples(25)
        record = composed_guard.guard(planned_campaign, null, real)
        assert record.method in ("exact", "asymptotic")
        assert record.measurement.null_count == 25
        assert record.measurement.real_count == 25
        assert record.measurement.method == record.method
        # ...and the same provenance comes back out of the store, so the row
        # an operator reads and the value the guard returned are one reading.
        reloaded = composed_guard.load(planned_campaign)
        assert reloaded.measurement == record.measurement

    def test_the_campaign_leaves_the_guard_still_calibrated(
        self, composed_guard, planned_campaign
    ) -> None:
        # The feature boundary, in the assembled system: §7.4's ``p < 0.05``
        # comparison and the ``VOID`` verdict are feature 124's. This feature
        # *measures*, so a campaign whose p-value is decisively detectable
        # comes out of the guard with its ``calibration_status`` untouched —
        # still ``'ok'`` by the migration's own default.
        null, real = samples(4, gap=5000.0)
        record = composed_guard.guard(planned_campaign, null, real)
        assert record.pvalue < 0.05, "this case must be one 124 would void on"
        with composed_guard._connect() as connection:
            row = connection.execute(
                "SELECT ks_pvalue, calibration_status FROM campaign WHERE id = ?",
                (planned_campaign,),
            ).fetchone()
        assert row[0] == record.pvalue
        assert row[1] == "ok"

    def test_the_campaigns_planning_columns_are_untouched(
        self, composed_guard, planned_campaign
    ) -> None:
        # The guard fills one column of a row that is not its own. The type,
        # ``W`` and ``φ`` are the planner's — ``φ`` is the number the whole
        # blinding discipline is built around — and a guard run that rewrote
        # any of them would be quietly redefining the campaign it measured.
        null, real = samples(20)
        composed_guard.guard(planned_campaign, null, real)
        with composed_guard._connect() as connection:
            row = connection.execute(
                "SELECT campaign_type, workspace_count, null_fraction, created_at "
                "FROM campaign WHERE id = ?",
                (planned_campaign,),
            ).fetchone()
        assert row[0:3] == campaign_row()
        assert row[3] is not None

    def test_an_unguarded_campaign_reads_as_unread_not_as_an_error(
        self, composed_guard, planned_campaign
    ) -> None:
        # The state a campaign is in between its planner writing the row and
        # the guard job running: created, not yet read. ``None`` is that
        # answer, and it must stay distinguishable from "tested, and
        # decisively detectable" — which is why the migration made the column
        # Nullable and why a ``NOT NULL`` there would have fabricated a zero.
        assert composed_guard.load(planned_campaign) is None
        with composed_guard._connect() as connection:
            row = connection.execute(
                "SELECT ks_pvalue FROM campaign WHERE id = ?", (planned_campaign,)
            ).fetchone()
        assert row[0] is None

    def test_a_re_guard_refreshes_rather_than_appending(
        self, composed_guard, planned_campaign
    ) -> None:
        # §7.4's own instruction is "investigate the block length and
        # permutation scheme before proceeding", so a campaign is expected to
        # be guarded more than once. The grain is the campaign, and what the
        # table holds is the latest reading and nothing else.
        first_null, first_real = samples(20)
        second_null, second_real = samples(28)
        composed_guard.guard(planned_campaign, first_null, first_real)
        second = composed_guard.guard(planned_campaign, second_null, second_real)
        with composed_guard._connect() as connection:
            rows = connection.execute(
                "SELECT campaign_id FROM campaign_ks_guard WHERE campaign_id = ?",
                (planned_campaign,),
            ).fetchall()
        assert len(rows) == 1
        assert composed_guard.load(planned_campaign) == second

    def test_the_verdict_of_detectability_is_reported_not_acted_on(
        self, composed_guard, planned_campaign
    ) -> None:
        # The p-value an operator would act on is available to them, and the
        # system has not acted on it. This is the boundary between this
        # feature and the next, expressed as the two things a caller can do
        # with the returned record: read the number, and hand it to 124.
        null, real = samples(6, gap=5000.0)
        record = composed_guard.guard(planned_campaign, null, real)
        assert record.pvalue < 0.05
        assert record.statistic > 0.9
        assert composed_guard.load(planned_campaign).pvalue == record.pvalue


class TestTheGuardRefusesWhatItCannotMeasure:
    def test_a_campaign_nobody_planned_is_refused(
        self, composed_guard, raised_named
    ) -> None:
        # A p-value is a fact *about a campaign*. A guard that wrote the
        # column onto a row it created would be inventing the campaign the
        # number belongs to — and ``φ``, the fraction the blinding discipline
        # is built on, is the planner's to fix.
        null, real = samples(10)
        with raised_named("KsGuardError"):
            composed_guard.guard(str(uuid.uuid4()), null, real)

    def test_a_sample_that_cannot_support_a_verdict_is_refused(
        self, composed_guard, planned_campaign, raised_named
    ) -> None:
        # §7.4's p-value voids a campaign, so a number computed from a sample
        # that never existed is worse than no number. A non-finite score is a
        # measurement that failed, and dropping it silently would compare two
        # distributions neither of which is the one the campaign produced.
        with raised_named("KsTestError"):
            composed_guard.guard(
                planned_campaign, [1.0, float("nan")], [3.0, 4.0]
            )

    def test_a_refused_sample_leaves_the_campaign_unread(
        self, composed_guard, planned_campaign, raised_named
    ) -> None:
        # The measurement runs before the store is opened, so a refusal
        # leaves the campaign exactly as it was: un-read, with no row
        # claiming the guard had run.
        with raised_named("KsTestError"):
            composed_guard.guard(planned_campaign, [1.0], [3.0, 4.0])
        assert composed_guard.load(planned_campaign) is None
        with composed_guard._connect() as connection:
            row = connection.execute(
                "SELECT ks_pvalue FROM campaign WHERE id = ?", (planned_campaign,)
            ).fetchone()
        assert row[0] is None

    def test_two_samples_naming_the_same_node_are_refused(
        self, composed_guard, planned_campaign, raised_named
    ) -> None:
        # A node's null status is one bit in §7.1's sidecar, so two samples
        # that disagree about it are not the two populations §7.4 compares —
        # and the p-value that followed would be about a partition the
        # campaign never had.
        nodes = [str(uuid.uuid4()) for _ in range(4)]
        sample = {nodes[0]: 1.0, nodes[1]: 2.0, nodes[2]: 3.0}
        with raised_named("KsTestError"):
            composed_guard.guard(
                planned_campaign, sample, {**sample, nodes[3]: 9.0}
            )
