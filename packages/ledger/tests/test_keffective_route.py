"""Feature 94: GET /ledger/k-effective — the deflation input, as a route.

``KEffectiveEndpoint.get`` is the feature's whole sentence — *System
exposes GET /ledger/k-effective which returns K_effective per epoch as the
deflation input* — and these tests hold it to each clause:

* **exposes GET /ledger/k-effective**: the route is spelled once
  (:data:`KEFFECTIVE_ROUTE`), carried on the class, and the member
  registers a ``ledger-k-effective`` component that the factory composes
  and the composed application hands out;
* **returns K_effective per epoch**: the answer is a breakdown — one
  ``(epoch, count)`` pair per observed epoch, unnamed first then ascending
  — with the epoch dimension following feature 88's stamp exactly as
  feature 93's derivation does;
* **as the deflation input**: the figures are the budget-charging counts
  and *not* the ledger's row count.  This is the clause with teeth —
  §10.3's score keeps ``−β₁·trials_charged`` and ``−β₃·deflation(K_eff)``
  as two separate terms — so the tests assert the route's total against
  both reads of the same ledger, and pin that anywhere a route could have
  reached for the plain count it does not: an all-null ledger answers
  ``0``, not the number of rows sitting in the table.

Two consequences the feature states rather than leaves to inference are
tested too: an epoch that charged nothing is *reported* at ``0`` rather
than omitted (a key a reader must infer is a key a reader can get wrong),
and neither an absent store nor an unreadable row is ever answered with a
number — the first composes no endpoint, the second raises, because a
deflation input that quietly fell back to zero understates ``K``, the one
direction that lets a false discovery through.
"""

from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest

import ledger
from app.module_loader import (
    Application,
    Registration,
    create_app,
    scan_components,
)
from ledger import (
    DATABASE_URL_ENV,
    KEFFECTIVE_COMPONENT_NAME,
    KEFFECTIVE_ROUTE,
    TRIAL_LEDGER_TABLE,
    KEffective,
    KEffectiveEndpoint,
    KEffectiveResponse,
    TrialLedger,
    TrialRecordError,
)

CAMPAIGN = uuid.uuid4()
OTHER_CAMPAIGN = uuid.uuid4()
STAMP = datetime(2026, 9, 20, 5, 0, 0, tzinfo=timezone.utc)
# The outcome these feature-94 tests charge with — any of the four would
# do; the outcome's own behaviour is test_outcome.py's subject, and the
# route's count is deliberately indifferent to it.
OUTCOME = "ok"

# The sequestered epoch these tests charge against: any name would do,
# and 'epoch-7' is the spelling the sealing tests coin.  The epoch's own
# behaviour — required at the write, refused when absent, ``None`` on a
# pre-stamp read — is test_epoch.py's subject.
EPOCH = "epoch-7"

# The provenance triple these tests charge under (feature 87): the frozen
# evaluator, the sealed snapshot and the cost model the trial ran against,
# each the sha256 hexdigest its owning feature computes.  The triple's own
# behaviour -- required at the write, refused when absent or malformed,
# normalised to lowercase hex, ``None`` on a pre-stamp read -- is
# test_provenance.py's subject; here it is spelled once as a mapping and
# handed to every charge with ``**``.
EVALUATOR_HASH = "27f6343f980c4c0ab821d9c72d211d0eb76b0853825cefd80476a05e43cab27e"
SNAPSHOT_HASH = "16a0eeb0791b6c92451fd284dd9f599e0a7dbe7f6ebea6e2d2d06c7f74aec112"
COST_MODEL_HASH = "7ceff1a68ddd995b2e87790bad3d75edd4bd42da19cf19039af8888851a7f520"
PROVENANCE = {
    "evaluator_hash": EVALUATOR_HASH,
    "snapshot_hash": SNAPSHOT_HASH,
    "cost_model_hash": COST_MODEL_HASH,
}


MEMBER_SRC = Path(ledger.__file__).resolve().parent.parent


def _node() -> uuid.UUID:
    """A fresh node identity — one evaluation, one charge, one row."""
    return uuid.uuid4()


def _legacy_unnamed_row(db_path: Path, budget: int = 1) -> None:
    """Write one pre-epoch row directly: a charge that names no epoch.

    A fresh row cannot be written epoch-less any more — feature 88's
    stamp is required at every write seam this store offers — so the one
    way to hold a row in the un-named epoch is the way the ledger itself
    came by them: the row predates the stamp.  The seven-column table is
    the schema this member wrote through features 86-91, and the row is
    inserted with raw SQL on purpose, exactly as the store's legacy
    upgrade finds such rows in the wild.
    """
    with sqlite3.connect(db_path) as connection:
        connection.executescript(f"""
        CREATE TABLE IF NOT EXISTS {TRIAL_LEDGER_TABLE} (
            seq             INTEGER PRIMARY KEY AUTOINCREMENT,
            ts              TEXT NOT NULL,
            node_id         TEXT NOT NULL,
            campaign_id     TEXT NOT NULL,
            outcome         TEXT NOT NULL,
            charges_budget  BOOLEAN NOT NULL,
            charge_units    REAL NOT NULL DEFAULT 1.0
        );
        """)
        connection.execute(
            f"INSERT INTO {TRIAL_LEDGER_TABLE} "
            "(ts, node_id, campaign_id, outcome, charges_budget, charge_units) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (STAMP.isoformat(), str(_node()), str(CAMPAIGN), "ok", budget, 1.0),
        )


@pytest.fixture
def test_k_endpoint(test_ledger: TrialLedger) -> KEffectiveEndpoint:
    """The GET /ledger/k-effective endpoint over this test's ledger.

    Bound to the same per-test database as ``test_ledger``, so a test can
    charge through one seam and read the route's answer against the same
    state.
    """
    return KEffectiveEndpoint(test_ledger)


# -- The route returns K_effective per epoch -----------------------------------


def test_the_route_returns_the_budget_charging_counts_per_epoch(
    test_k_endpoint: KEffectiveEndpoint,
    test_ledger: TrialLedger,
) -> None:
    # The whole sentence at once: two epochs, counted by the directive
    # that was stamped on each row, with the epoch the row charged
    # deciding the grouping.
    for budget, epoch in ((True, "epoch-7"), (False, "epoch-7"), (True, "epoch-8")):
        test_ledger.append(_node(), CAMPAIGN, OUTCOME, budget, ts=STAMP, epoch_id=epoch, **PROVENANCE)

    response = test_k_endpoint.get()
    assert response.counts == (("epoch-7", 1), ("epoch-8", 1))
    assert response.of("epoch-7") == 1
    assert response.of("epoch-8") == 1
    assert response.total == 2


def test_a_pre_stamp_table_answers_one_unnamed_bucket(
    test_k_endpoint: KEffectiveEndpoint, test_ledger: TrialLedger, db_path: Path
) -> None:
    # A table written before feature 88's stamp landed holds rows that
    # name no epoch, so the route answers one honest bucket — labelled as
    # naming no epoch rather than pretending to be one — and answers a
    # genuine per-epoch view over the rows the store writes now, with no
    # edit to the route.
    _legacy_unnamed_row(db_path, budget=1)
    _legacy_unnamed_row(db_path, budget=0)

    response = test_k_endpoint.get()
    assert response.counts == ((None, 1),)
    assert response.of(None) == 1
    assert response.of("never-run") == 0


def test_an_all_null_epoch_is_reported_at_zero_not_omitted(
    test_k_endpoint: KEffectiveEndpoint, test_ledger: TrialLedger
) -> None:
    # The deflation term must be *told* that an epoch contributed no
    # degrees of freedom.  A route that listed only the epochs that
    # charged budget would leave that fact to be inferred from a missing
    # key — and a key a reader has to infer is a key a reader can silently
    # get wrong.
    test_ledger.append(_node(), CAMPAIGN, OUTCOME, True, ts=STAMP, epoch_id="epoch-7", **PROVENANCE)
    test_ledger.append(_node(), CAMPAIGN, OUTCOME, False, ts=STAMP, epoch_id="epoch-8", **PROVENANCE)

    response = test_k_endpoint.get()
    assert response.of("epoch-8") == 0
    assert ("epoch-8", 0) in response.counts
    assert response.view.by_epoch == {"epoch-7": 1, "epoch-8": 0}


def test_the_route_orders_the_unnamed_epoch_first(
    test_k_endpoint: KEffectiveEndpoint, test_ledger: TrialLedger, db_path: Path
) -> None:
    # One order, stated by the derivation and passed through by the route:
    # the un-named epoch first, then ascending epoch spelling — so two
    # reads over the same log are equal values and read back alike.  The
    # un-named bucket needs a pre-stamp row: every row the store writes
    # now names its epoch.
    _legacy_unnamed_row(db_path)
    test_ledger.append(_node(), CAMPAIGN, OUTCOME, True, ts=STAMP, epoch_id="epoch-8", **PROVENANCE)
    test_ledger.append(_node(), CAMPAIGN, OUTCOME, True, ts=STAMP, epoch_id="epoch-7", **PROVENANCE)

    assert test_k_endpoint.get().counts == ((None, 1), ("epoch-7", 1), ("epoch-8", 1))


def test_an_empty_ledger_answers_an_honest_zero(
    test_k_endpoint: KEffectiveEndpoint, test_ledger: TrialLedger
) -> None:
    # No rows at all: no epochs observed, no budget charged.  A scoring
    # process asking before any trial ran gets a zero rather than an
    # error — the same stance the store takes toward an absent store.
    response = test_k_endpoint.get()
    assert response.counts == ()
    assert response.total == 0
    assert len(response) == 0
    assert bool(response.view) is False
    assert test_ledger.count() == 0


# -- "as the deflation input": the route is not the row count -------------------


def test_the_route_returns_k_effective_and_not_the_row_count(
    test_k_endpoint: KEffectiveEndpoint, test_ledger: TrialLedger
) -> None:
    # §10.3's score penalizes trials_charged (β₁) and deflates by
    # K_effective (β₃) as two separate terms, so the two numbers must not
    # be interchangeable.  Asserted against one ledger read two ways: the
    # route disagrees with the plain count by exactly the null nodes, and
    # a route that had reached for the count could not pass.
    for budget in (True, False, False, True, False):
        test_ledger.append(_node(), CAMPAIGN, OUTCOME, budget, ts=STAMP, epoch_id=EPOCH, **PROVENANCE)

    response = test_k_endpoint.get()
    assert response.total == 2
    assert test_ledger.count() == 5
    assert test_ledger.count() - response.total == 3  # the null nodes


def test_a_ledger_of_nothing_but_null_nodes_answers_zero_not_its_rows(
    test_k_endpoint: KEffectiveEndpoint, test_ledger: TrialLedger
) -> None:
    # The sharp end of the clause: rows exist, budget charged is nil, and
    # the deflation input is 0.  A route that answered the row count would
    # inflate the deflation term by every null node a campaign ran —
    # silently, under a route name that promises the opposite.
    for _ in range(4):
        test_ledger.append(_node(), CAMPAIGN, OUTCOME, False, ts=STAMP, epoch_id=EPOCH, **PROVENANCE)

    response = test_k_endpoint.get()
    assert response.total == 0
    assert test_ledger.count() == 4
    assert bool(response.view) is False


def test_null_nodes_never_move_the_routes_figure(
    test_k_endpoint: KEffectiveEndpoint, test_ledger: TrialLedger
) -> None:
    # The feature's own point, as arithmetic on the route's answer:
    # charging any number of null nodes leaves it exactly where it was.
    test_ledger.append(_node(), CAMPAIGN, OUTCOME, True, ts=STAMP, epoch_id=EPOCH, **PROVENANCE)
    before = test_k_endpoint.get().total
    for _ in range(25):
        test_ledger.append(_node(), CAMPAIGN, OUTCOME, False, ts=STAMP, epoch_id=EPOCH, **PROVENANCE)

    assert before == 1
    assert test_k_endpoint.get().total == 1
    assert test_ledger.count() == 26


@pytest.mark.parametrize("outcome", ["ok", "timeout", "error", "tripwire_fail"])
def test_the_routes_count_is_of_outcomes_not_of_successes(
    test_k_endpoint: KEffectiveEndpoint, test_ledger: TrialLedger, outcome: str
) -> None:
    # §6.1's step 11 debits even when the node fails, so a failed trial
    # consumed a hypothesis exactly as a successful one did.  Only
    # charges_budget decides this filter; the outcome never does.
    test_ledger.append(_node(), CAMPAIGN, outcome, True, ts=STAMP, epoch_id=EPOCH, **PROVENANCE)
    assert test_k_endpoint.get().total == 1


def test_the_same_epoch_across_two_campaigns_is_one_epoch_on_the_route(
    test_k_endpoint: KEffectiveEndpoint, test_ledger: TrialLedger
) -> None:
    # Sequestered epochs are a global, non-renewable resource (§6.1), so
    # two campaigns' trials in one epoch spend the same degrees of freedom
    # and the route counts them together.
    test_ledger.append(
        _node(), CAMPAIGN, OUTCOME, True, ts=STAMP, epoch_id="epoch-7", **PROVENANCE
    )
    test_ledger.append(
        _node(), OTHER_CAMPAIGN, OUTCOME, True, ts=STAMP, epoch_id="epoch-7", **PROVENANCE
    )
    assert test_k_endpoint.get().of("epoch-7") == 2


def test_the_route_answers_the_ledgers_state_at_the_moment_it_is_asked(
    test_k_endpoint: KEffectiveEndpoint, test_ledger: TrialLedger
) -> None:
    # No cache: a campaign that charges a trial between two reads must
    # move the second answer.  A memoised total would make the deflation
    # term depend on when the scoring process happened to start.
    assert test_k_endpoint.get().total == 0
    test_ledger.append(_node(), CAMPAIGN, OUTCOME, True, ts=STAMP, epoch_id=EPOCH, **PROVENANCE)
    assert test_k_endpoint.get().total == 1
    test_ledger.append(_node(), CAMPAIGN, OUTCOME, False, ts=STAMP, epoch_id=EPOCH, **PROVENANCE)
    assert test_k_endpoint.get().total == 1


def test_a_debit_charges_budget_the_same_way_through_the_route(
    test_ledger: TrialLedger, test_endpoint
) -> None:
    # The two routes are two views of one table: feature 95's charge lands
    # on the row, and the row is what feature 94's read counts.
    test_endpoint.post(
        ledger.DebitRequest(_node(), CAMPAIGN, OUTCOME, True, epoch_id=EPOCH, **PROVENANCE)
    )
    test_endpoint.post(
        ledger.DebitRequest(_node(), CAMPAIGN, OUTCOME, False, epoch_id=EPOCH, **PROVENANCE)
    )
    assert KEffectiveEndpoint(test_ledger).get().total == 1


# -- The response is feature 93's derivation, framed ---------------------------


def test_the_response_agrees_with_the_store_read(
    test_k_endpoint: KEffectiveEndpoint, test_ledger: TrialLedger
) -> None:
    # One answer drawn one way: the route never re-derives, so the two
    # cannot disagree — asserted against the store rather than through the
    # route alone.
    for budget in (True, False, True):
        test_ledger.append(_node(), CAMPAIGN, OUTCOME, budget, ts=STAMP, epoch_id=EPOCH, **PROVENANCE)

    response = test_k_endpoint.get()
    view = test_ledger.k_effective()
    assert response.view == view
    assert response.counts == view.counts
    assert response.total == view.total
    assert response.of(None) == view.of(None)


def test_the_response_hands_back_the_derivations_rest(
    test_k_endpoint: KEffectiveEndpoint, test_ledger: TrialLedger
) -> None:
    # Everything feature 93 states is reachable through the response's
    # view rather than respelled on the route: by_epoch, epochs, and the
    # per-epoch read.
    test_ledger.append(_node(), CAMPAIGN, OUTCOME, True, ts=STAMP, epoch_id="epoch-7", **PROVENANCE)
    test_ledger.append(_node(), CAMPAIGN, OUTCOME, False, ts=STAMP, epoch_id="epoch-8", **PROVENANCE)

    view = test_k_endpoint.get().view
    assert isinstance(view, KEffective)
    assert view.by_epoch == {"epoch-7": 1, "epoch-8": 0}
    assert view.epochs == ("epoch-7", "epoch-8")


def test_the_response_reports_how_many_epochs_it_carries(
    test_k_endpoint: KEffectiveEndpoint, test_ledger: TrialLedger
) -> None:
    # The size of the breakdown — the "per epoch" dimension of the
    # clause, readable without walking the pairs.
    for epoch in ("epoch-7", "epoch-8", "epoch-8"):
        test_ledger.append(_node(), CAMPAIGN, OUTCOME, True, ts=STAMP, epoch_id=epoch, **PROVENANCE)
    assert len(test_k_endpoint.get()) == 2


def test_the_total_cannot_drift_from_the_pairs_it_sums(
    test_k_endpoint: KEffectiveEndpoint, test_ledger: TrialLedger
) -> None:
    for epoch in ("epoch-7", "epoch-8"):
        test_ledger.append(_node(), CAMPAIGN, OUTCOME, True, ts=STAMP, epoch_id=epoch, **PROVENANCE)
    test_ledger.append(_node(), CAMPAIGN, OUTCOME, False, ts=STAMP, epoch_id="epoch-8", **PROVENANCE)

    response = test_k_endpoint.get()
    assert response.total == sum(count for _, count in response.counts) == 2


def test_the_response_refuses_something_that_is_not_a_derivation() -> None:
    # A response is the deflation input, so it is drawn from feature 93's
    # derivation and never from a plain count — the same discipline the
    # endpoint applies to the store, applied to the value it hands out.
    with pytest.raises(TypeError, match="KEffective"):
        KEffectiveResponse(view=5)  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="KEffective"):
        KEffectiveResponse(view=object())  # type: ignore[arg-type]


def test_the_response_is_frozen() -> None:
    response = KEffectiveResponse(KEffective((("epoch-7", 1),)))
    with pytest.raises(AttributeError):
        response.view = KEffective(())  # type: ignore[misc]


def test_an_equal_derivation_gives_an_equal_response() -> None:
    a = KEffectiveResponse(KEffective((("epoch-7", 1), ("epoch-8", 0))))
    b = KEffectiveResponse(KEffective((("epoch-8", 0), ("epoch-7", 1))))
    assert a == b
    assert a.counts == b.counts


# -- Refusals: nothing this route did not read is ever answered -----------------


def test_a_corrupted_directive_is_refused_by_the_route(
    test_k_endpoint: KEffectiveEndpoint, test_ledger: TrialLedger, db_path: Path
) -> None:
    # A stored directive that wandered off the bit makes the route refuse
    # rather than under-count.  The alternative — skipping it, or treating
    # it as "not true" — silently shrinks the deflation input, the one
    # direction the honest counter must never move by accident.
    test_ledger.append(_node(), CAMPAIGN, OUTCOME, True, ts=STAMP, epoch_id=EPOCH, **PROVENANCE)
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            f"UPDATE {TRIAL_LEDGER_TABLE} SET charges_budget = 2 WHERE seq = 1"
        )
    with pytest.raises(TrialRecordError, match="charges_budget must be a bool"):
        test_k_endpoint.get()


def test_the_route_never_answers_a_read_that_failed(
    test_ledger: TrialLedger, db_path: Path
) -> None:
    # A configured store whose read fails propagates: the endpoint adds no
    # fallback and catches nothing, because every fallback it could add is
    # a deflation input the ledger never stated — and a zero would read as
    # "this campaign consumed no statistical budget", the one direction
    # that lets a false discovery through.  The failure is real (the file
    # is no longer a database), so an endpoint that swallowed it and
    # answered 0 could not pass.
    test_ledger.append(_node(), CAMPAIGN, OUTCOME, True, ts=STAMP, epoch_id=EPOCH, **PROVENANCE)
    db_path.write_bytes(b"this is not a database")

    with pytest.raises(sqlite3.Error):
        KEffectiveEndpoint(test_ledger).get()


def test_the_endpoint_refuses_something_without_a_k_effective_seam() -> None:
    # A store that can only count rows is refused here rather than
    # answering the route with the number §10.3 penalizes separately (β₁).
    with pytest.raises(TypeError, match="k_effective"):
        KEffectiveEndpoint(object())  # type: ignore[arg-type]


def test_the_endpoint_refuses_a_bare_count() -> None:
    class CountOnly:
        def count(self) -> int:
            return 7

    with pytest.raises(TypeError, match="k_effective"):
        KEffectiveEndpoint(CountOnly())  # type: ignore[arg-type]


# -- Construction: from_env, resolve, one database ------------------------------


def test_from_env_resolves_the_configured_ledger(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(DATABASE_URL_ENV, "sqlite:///somewhere/ledger.db")
    endpoint = KEffectiveEndpoint.from_env()
    assert endpoint is not None
    assert endpoint.ledger.database_url == "sqlite:///somewhere/ledger.db"
    assert endpoint.route == KEFFECTIVE_ROUTE


@pytest.mark.parametrize("blank", ["", "   "])
def test_from_env_treats_blank_as_absent(
    monkeypatch: pytest.MonkeyPatch, blank: str
) -> None:
    monkeypatch.setenv(DATABASE_URL_ENV, blank)
    assert KEffectiveEndpoint.from_env() is None


def test_from_env_reads_a_handed_environment_over_the_process_one() -> None:
    endpoint = KEffectiveEndpoint.from_env({DATABASE_URL_ENV: "sqlite:///handed.db"})
    assert endpoint is not None
    assert endpoint.ledger.database_url == "sqlite:///handed.db"


def test_from_env_composes_no_endpoint_without_a_store(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(DATABASE_URL_ENV, raising=False)
    assert KEffectiveEndpoint.from_env() is None


# -- Registration, composition -------------------------------------------------


def test_the_route_is_spelled_once_everywhere() -> None:
    assert KEFFECTIVE_ROUTE == "/ledger/k-effective"
    assert KEffectiveEndpoint.route == KEFFECTIVE_ROUTE


def test_the_scan_registers_the_k_effective_component() -> None:
    registry = Registration()
    components = scan_components(MEMBER_SRC, registry=registry)
    names = [component.name for component in components]
    assert KEFFECTIVE_COMPONENT_NAME in names
    assert KEFFECTIVE_COMPONENT_NAME == "ledger-k-effective"
    # The two earlier registrations are unchanged: one ledger, and one
    # debit endpoint beside this read.
    assert names.count("ledger") == 1
    assert names.count("ledger-debit") == 1


def test_the_composed_app_builds_the_k_effective_endpoint(
    test_database_url: str,
) -> None:
    app = create_app(MEMBER_SRC, registry=Registration())
    component = app.get(KEFFECTIVE_COMPONENT_NAME)
    assert component is not None
    assert callable(component.get)
    assert component.route == KEFFECTIVE_ROUTE
    assert component.ledger.database_url == test_database_url
    assert KEFFECTIVE_COMPONENT_NAME in app.order


def test_the_builder_contributes_nothing_without_a_store(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(DATABASE_URL_ENV, raising=False)
    app = create_app(MEMBER_SRC, registry=Registration())
    assert app.get(KEFFECTIVE_COMPONENT_NAME) is None


def test_the_route_the_debit_and_the_store_compose_over_one_database(
    test_database_url: str,
) -> None:
    # One resolution, one database: the composed read serves the figures
    # of the very ledger the composed "ledger" component names and the
    # composed debit endpoint charges, so a deployment can never charge
    # one table while deflating by another.
    app = create_app(MEMBER_SRC, registry=Registration())
    endpoint = app.get(KEFFECTIVE_COMPONENT_NAME)
    debiter = app.get(ledger.DEBIT_COMPONENT_NAME)
    store = app.get("ledger")
    assert endpoint.ledger.database_url == store.database_url
    assert endpoint.ledger.database_url == debiter.ledger.database_url

    debiter.post(ledger.DebitRequest(_node(), CAMPAIGN, OUTCOME, True, epoch_id=EPOCH, **PROVENANCE))
    debiter.post(ledger.DebitRequest(_node(), CAMPAIGN, OUTCOME, False, epoch_id=EPOCH, **PROVENANCE))
    assert endpoint.get().total == 1
    assert store.count() == 2


def test_an_absent_k_effective_component_is_none_rather_than_an_error() -> None:
    assert Application().get(KEFFECTIVE_COMPONENT_NAME) is None


def test_the_endpoint_duck_accepts_the_composed_component(
    test_database_url: str,
) -> None:
    # The factory's scan imports the member under an alias module, so the
    # composed store answers with a KEffective that is structurally this
    # one but never the same class object a direct import yields — the
    # endpoint and its response must take it anyway (the seam is the
    # contract, not the class identity).
    app = create_app(MEMBER_SRC, registry=Registration())
    composed = app.get("ledger")
    endpoint = KEffectiveEndpoint(composed)  # type: ignore[arg-type]
    composed.append(_node(), CAMPAIGN, OUTCOME, True, epoch_id=EPOCH, **PROVENANCE)
    response = endpoint.get()
    assert response.total == 1
    assert KEffectiveResponse(response.view).counts == ((EPOCH, 1),)
