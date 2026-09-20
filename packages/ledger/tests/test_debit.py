"""Feature 95: POST /ledger/debit — the idempotent charge, keyed by node.

``DebitEndpoint.post`` is the feature's whole sentence — *System exposes
POST /ledger/debit appending one trial row idempotently keyed by
node_id, which returns the prior sequence on a retry* — and these tests
hold it to each clause:

* **appending one trial row**: the first POST for a node appends exactly
  one row, spends exactly one sequence number, and the response's
  record is the row the table holds;
* **idempotently keyed by node_id**: a retry appends nothing — the count
  does not move, the retry spends no sequence number (the next node's
  first debit draws the very next number), and the idempotence is drawn
  from the table, not from the endpoint's memory, so it survives the
  process that first debited;
* **returns the prior sequence on a retry**: the retry's ``seq`` is the
  row's own sequence — the number the original POST returned — and only
  ``appended`` differs between the two responses;
* **the race the contract is really about**: concurrent POSTs for one
  node — the spot-reclaimed worker's retry overlapping the original
  (§14: "Failures retry; ledger debits are idempotent by ``node_id``")
  — serialise onto exactly one row.

The store seam (``TrialLedger.debit``) is pinned alongside the endpoint,
because that is where the check-and-insert is one transaction; and the
registration chain — member, factory, seat — is pinned so the route
cannot silently fall out of the composed application.
"""

from __future__ import annotations

import uuid
from concurrent.futures import ThreadPoolExecutor
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
from app.modules import ledger as ledger_seat
from ledger import (
    DATABASE_URL_ENV,
    DEBIT_COMPONENT_NAME,
    DEBIT_ROUTE,
    DebitEndpoint,
    DebitRequest,
    DebitResponse,
    TrialLedger,
    TrialLedgerRecord,
    TrialRecordError,
)

NODE_A = uuid.uuid4()
NODE_B = uuid.uuid4()
CAMPAIGN = uuid.uuid4()
STAMP = datetime(2026, 9, 20, 5, 0, 0, tzinfo=timezone.utc)
LATER = datetime(2026, 9, 20, 6, 0, 0, tzinfo=timezone.utc)
# The outcome these feature-95 tests charge with — any of the four
# would do; the outcome's own behaviour is test_outcome.py's subject.
OUTCOME = "ok"
CHARGES_BUDGET = True

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


# -- The first POST appends one row ------------------------------------------


def test_the_first_post_appends_one_row(test_endpoint: DebitEndpoint) -> None:
    response = test_endpoint.post(DebitRequest(NODE_A, CAMPAIGN, OUTCOME, CHARGES_BUDGET, epoch_id=EPOCH, **PROVENANCE))
    assert response.appended is True
    assert response.retry is False
    assert response.seq == 1
    assert response.record == TrialLedgerRecord(
        seq=1, ts=response.record.ts, node_id=NODE_A, campaign_id=CAMPAIGN, outcome=OUTCOME, charges_budget=CHARGES_BUDGET, epoch_id=EPOCH, **PROVENANCE)


def test_the_first_post_spends_exactly_one_row_and_number(
    test_endpoint: DebitEndpoint, test_ledger: TrialLedger
) -> None:
    test_endpoint.post(DebitRequest(NODE_A, CAMPAIGN, OUTCOME, CHARGES_BUDGET, epoch_id=EPOCH, **PROVENANCE))
    assert test_ledger.count() == 1
    assert test_ledger.get(1) is not None


def test_distinct_nodes_append_distinct_rows(
    test_endpoint: DebitEndpoint, test_ledger: TrialLedger
) -> None:
    first = test_endpoint.post(DebitRequest(NODE_A, CAMPAIGN, OUTCOME, CHARGES_BUDGET, epoch_id=EPOCH, **PROVENANCE))
    second = test_endpoint.post(DebitRequest(NODE_B, CAMPAIGN, OUTCOME, CHARGES_BUDGET, epoch_id=EPOCH, **PROVENANCE))
    assert (first.seq, second.seq) == (1, 2)
    assert test_ledger.count() == 2


def test_the_response_record_is_the_row_the_table_holds(
    test_endpoint: DebitEndpoint, test_ledger: TrialLedger
) -> None:
    response = test_endpoint.post(DebitRequest(NODE_A, CAMPAIGN, OUTCOME, CHARGES_BUDGET, epoch_id=EPOCH, **PROVENANCE))
    assert test_ledger.get(response.seq) == response.record
    assert test_ledger.rows() == (response.record,)


# -- The retry: prior sequence, no second row ---------------------------------


def test_a_retry_returns_the_prior_sequence(
    test_endpoint: DebitEndpoint, test_ledger: TrialLedger
) -> None:
    # The worker died after the row landed but before the response made
    # it back; the worker that takes over posts the same charge again.
    original = test_endpoint.post(DebitRequest(NODE_A, CAMPAIGN, OUTCOME, CHARGES_BUDGET, epoch_id=EPOCH, **PROVENANCE))
    retry = test_endpoint.post(DebitRequest(NODE_A, CAMPAIGN, OUTCOME, CHARGES_BUDGET, epoch_id=EPOCH, **PROVENANCE))

    assert retry.seq == original.seq == 1
    assert retry.appended is False
    assert retry.retry is True
    assert retry.record == original.record
    assert test_ledger.count() == 1


def test_a_retry_spends_no_sequence_number(
    test_endpoint: DebitEndpoint, test_ledger: TrialLedger
) -> None:
    # The property that makes the retry free rather than merely
    # invisible: the skipped charge burns nothing, so the next node's
    # first debit draws the very next number.
    test_endpoint.post(DebitRequest(NODE_A, CAMPAIGN, OUTCOME, CHARGES_BUDGET, epoch_id=EPOCH, **PROVENANCE))
    test_endpoint.post(DebitRequest(NODE_A, CAMPAIGN, OUTCOME, CHARGES_BUDGET, epoch_id=EPOCH, **PROVENANCE))
    other = test_endpoint.post(DebitRequest(NODE_B, CAMPAIGN, OUTCOME, CHARGES_BUDGET, epoch_id=EPOCH, **PROVENANCE))

    assert other.seq == 2
    assert [row.seq for row in test_ledger.rows()] == [1, 2]


def test_repeated_retries_keep_returning_the_prior_sequence(
    test_endpoint: DebitEndpoint, test_ledger: TrialLedger
) -> None:
    first = test_endpoint.post(DebitRequest(NODE_A, CAMPAIGN, OUTCOME, CHARGES_BUDGET, epoch_id=EPOCH, **PROVENANCE))
    for _ in range(5):
        retry = test_endpoint.post(DebitRequest(NODE_A, CAMPAIGN, OUTCOME, CHARGES_BUDGET, epoch_id=EPOCH, **PROVENANCE))
        assert retry.seq == first.seq
        assert retry.appended is False
    assert test_ledger.count() == 1


def test_the_idempotence_survives_the_process_that_debited(
    test_database_url: str,
) -> None:
    # The endpoint holds no memo: the row in the table is the only record
    # of what was charged.  A brand-new store and endpoint — the next
    # process, as far as the ledger is concerned — recognises the retry.
    first = DebitEndpoint(TrialLedger(test_database_url))
    original = first.post(DebitRequest(NODE_A, CAMPAIGN, OUTCOME, CHARGES_BUDGET, epoch_id=EPOCH, **PROVENANCE))

    second = DebitEndpoint(TrialLedger(test_database_url))
    retry = second.post(DebitRequest(NODE_A, CAMPAIGN, OUTCOME, CHARGES_BUDGET, epoch_id=EPOCH, **PROVENANCE))

    assert retry.seq == original.seq
    assert retry.appended is False
    assert second.ledger.count() == 1


def test_a_retry_interleaved_with_other_charges_still_finds_its_row(
    test_endpoint: DebitEndpoint, test_ledger: TrialLedger
) -> None:
    a = test_endpoint.post(DebitRequest(NODE_A, CAMPAIGN, OUTCOME, CHARGES_BUDGET, epoch_id=EPOCH, **PROVENANCE))
    test_endpoint.post(DebitRequest(NODE_B, CAMPAIGN, OUTCOME, CHARGES_BUDGET, epoch_id=EPOCH, **PROVENANCE))
    retry = test_endpoint.post(DebitRequest(NODE_A, CAMPAIGN, OUTCOME, CHARGES_BUDGET, epoch_id=EPOCH, **PROVENANCE))

    assert retry.seq == a.seq == 1
    assert test_ledger.count() == 2
    assert [row.node_id for row in test_ledger.rows()] == [
        str(NODE_A),
        str(NODE_B),
    ]


# -- The race: a retry overlapping the original -------------------------------


def test_concurrent_posts_of_one_node_append_exactly_one_row(
    test_endpoint: DebitEndpoint, test_ledger: TrialLedger
) -> None:
    # The original and its retry in flight at once — the spot reclamation
    # case §14 states the contract for.  The check-and-insert is one
    # statement in one transaction, so the posts serialise on the
    # database's write lock: exactly one appends, every other caller is
    # answered by its row.
    request = DebitRequest(NODE_A, CAMPAIGN, OUTCOME, CHARGES_BUDGET, epoch_id=EPOCH, **PROVENANCE)
    with ThreadPoolExecutor(max_workers=8) as pool:
        responses = [
            pool.submit(test_endpoint.post, request).result()
            for _ in range(8)
        ]

    assert test_ledger.count() == 1
    assert {response.seq for response in responses} == {1}
    assert sum(1 for response in responses if response.appended) == 1


# -- The stamp on a retry ------------------------------------------------------


def test_an_explicit_stamp_is_persisted_on_the_first_post(
    test_endpoint: DebitEndpoint, test_ledger: TrialLedger
) -> None:
    response = test_endpoint.post(DebitRequest(NODE_A, CAMPAIGN, OUTCOME, CHARGES_BUDGET, ts=STAMP, epoch_id=EPOCH, **PROVENANCE))
    assert response.record.ts == STAMP
    assert test_ledger.get(response.seq) == response.record


def test_a_retry_does_not_restate_the_charge(
    test_endpoint: DebitEndpoint, test_ledger: TrialLedger
) -> None:
    # Append-only accounting: the prior row stands exactly as first
    # written.  A retry carrying a different stamp loses — silently, by
    # design, because the row is a fact and facts are never restated;
    # the response's record says which stamp landed.
    test_endpoint.post(DebitRequest(NODE_A, CAMPAIGN, OUTCOME, CHARGES_BUDGET, ts=STAMP, epoch_id=EPOCH, **PROVENANCE))
    retry = test_endpoint.post(DebitRequest(NODE_A, CAMPAIGN, OUTCOME, CHARGES_BUDGET, ts=LATER, epoch_id=EPOCH, **PROVENANCE))

    assert retry.record.ts == STAMP
    assert test_ledger.get(1).ts == STAMP
    assert test_ledger.count() == 1


def test_the_default_clock_stamps_the_first_post(test_endpoint: DebitEndpoint) -> None:
    from ledger import utc_now

    before = utc_now()
    response = test_endpoint.post(DebitRequest(NODE_A, CAMPAIGN, OUTCOME, CHARGES_BUDGET, epoch_id=EPOCH, **PROVENANCE))
    after = utc_now()
    assert before <= response.record.ts <= after


def test_the_endpoint_routes_its_own_clock_to_the_store(
    test_endpoint: DebitEndpoint,
) -> None:
    def frozen() -> datetime:
        return STAMP

    response = test_endpoint.post(
        DebitRequest(NODE_A, CAMPAIGN, OUTCOME, CHARGES_BUDGET, epoch_id=EPOCH, **PROVENANCE), clock=frozen
    )
    assert response.record.ts == STAMP


# -- The request: validated at construction, before the store is touched -------


def test_the_request_canonicalises_whatever_spelled_the_identities(
    test_endpoint: DebitEndpoint,
) -> None:
    request = DebitRequest(str(NODE_A).upper(), CAMPAIGN.hex, OUTCOME, CHARGES_BUDGET, epoch_id=EPOCH, **PROVENANCE)
    assert request.node_id == str(NODE_A)
    assert request.campaign_id == str(CAMPAIGN)
    assert request.key == str(NODE_A)

    response = test_endpoint.post(request)
    assert response.record.node_id == str(NODE_A)
    assert response.record.campaign_id == str(CAMPAIGN)


def test_equal_requests_are_one_charge(
    test_endpoint: DebitEndpoint, test_ledger: TrialLedger
) -> None:
    # However the caller came by the identities, one key is one charge.
    first = test_endpoint.post(DebitRequest(NODE_A, CAMPAIGN, OUTCOME, CHARGES_BUDGET, epoch_id=EPOCH, **PROVENANCE))
    retry = test_endpoint.post(DebitRequest(str(NODE_A), str(CAMPAIGN), OUTCOME, CHARGES_BUDGET, epoch_id=EPOCH, **PROVENANCE))
    assert DebitRequest(NODE_A, CAMPAIGN, OUTCOME, CHARGES_BUDGET, epoch_id=EPOCH, **PROVENANCE) == DebitRequest(
        str(NODE_A), CAMPAIGN, OUTCOME, CHARGES_BUDGET, epoch_id=EPOCH, **PROVENANCE)
    assert retry.seq == first.seq
    assert test_ledger.count() == 1


@pytest.mark.parametrize(
    "node, campaign",
    [
        ("not-a-uuid", str(CAMPAIGN)),
        (str(NODE_A), "not-a-uuid"),
        (None, str(CAMPAIGN)),
        (str(NODE_A), 1234),
    ],
)
def test_a_malformed_request_is_refused_and_spends_no_sequence_number(
    test_endpoint: DebitEndpoint,
    test_ledger: TrialLedger,
    node: object,
    campaign: object,
) -> None:
    with pytest.raises(TrialRecordError):
        DebitRequest(node, campaign, epoch_id=EPOCH, **PROVENANCE)  # type: ignore[arg-type]
    assert test_ledger.count() == 0


def test_a_naive_stamp_is_refused_at_the_request(
    test_endpoint: DebitEndpoint, test_ledger: TrialLedger
) -> None:
    with pytest.raises(TrialRecordError, match="timezone-aware"):
        DebitRequest(NODE_A, CAMPAIGN, OUTCOME, CHARGES_BUDGET, ts=datetime(2026, 9, 20, 5, 0, 0), epoch_id=EPOCH, **PROVENANCE)
    assert test_ledger.count() == 0


def test_a_request_stamp_in_another_offset_is_normalised(
    test_endpoint: DebitEndpoint,
) -> None:
    from datetime import timedelta

    aedt = timezone(timedelta(hours=10))
    request = DebitRequest(
        NODE_A, CAMPAIGN, OUTCOME, CHARGES_BUDGET, ts=datetime(2026, 9, 20, 15, 0, 0, tzinfo=aedt), epoch_id=EPOCH, **PROVENANCE)
    assert request.ts == STAMP


# -- The response is a frozen fact ---------------------------------------------


def test_the_response_and_request_are_frozen() -> None:
    request = DebitRequest(NODE_A, CAMPAIGN, OUTCOME, CHARGES_BUDGET, epoch_id=EPOCH, **PROVENANCE)
    response = DebitResponse(
        appended=True,
        record=TrialLedgerRecord(
            seq=1, ts=STAMP, node_id=NODE_A, campaign_id=CAMPAIGN, outcome=OUTCOME, charges_budget=CHARGES_BUDGET, epoch_id=EPOCH, **PROVENANCE),
    )
    with pytest.raises(AttributeError):
        request.node_id = "edited"  # type: ignore[misc]
    with pytest.raises(AttributeError):
        response.appended = False  # type: ignore[misc]


def test_the_response_seq_cannot_drift_from_the_record() -> None:
    response = DebitResponse(
        appended=False,
        record=TrialLedgerRecord(
            seq=7, ts=STAMP, node_id=NODE_A, campaign_id=CAMPAIGN, outcome=OUTCOME, charges_budget=CHARGES_BUDGET, epoch_id=EPOCH, **PROVENANCE),
    )
    assert response.seq == 7
    assert response.retry is True


# -- The store seam: TrialLedger.debit ------------------------------------------


def test_the_store_debit_appends_then_answers_with_the_prior_row(
    test_ledger: TrialLedger,
) -> None:
    record, appended = test_ledger.debit(NODE_A, CAMPAIGN, OUTCOME, CHARGES_BUDGET, ts=STAMP, epoch_id=EPOCH, **PROVENANCE)
    assert appended is True
    assert record.seq == 1

    prior, appended_again = test_ledger.debit(NODE_A, CAMPAIGN, OUTCOME, CHARGES_BUDGET, ts=LATER, epoch_id=EPOCH, **PROVENANCE)
    assert appended_again is False
    assert prior == record
    assert test_ledger.count() == 1


def test_the_store_debit_picks_the_earliest_row_when_raw_appends_left_several(
    test_ledger: TrialLedger,
) -> None:
    # Only the raw feature-86 append can leave one node holding several
    # rows.  When it has, the debit is answered by the earliest — the
    # first charge ever debited for the node is the one whose retry this
    # is — and appends nothing.
    test_ledger.append(NODE_A, CAMPAIGN, OUTCOME, CHARGES_BUDGET, ts=STAMP, epoch_id=EPOCH, **PROVENANCE)
    test_ledger.append(NODE_A, CAMPAIGN, OUTCOME, CHARGES_BUDGET, ts=LATER, epoch_id=EPOCH, **PROVENANCE)

    prior, appended = test_ledger.debit(NODE_A, CAMPAIGN, OUTCOME, CHARGES_BUDGET, epoch_id=EPOCH, **PROVENANCE)

    assert appended is False
    assert prior.seq == 1
    assert prior.ts == STAMP
    assert test_ledger.count() == 2


def test_the_store_debit_validates_before_the_database_is_touched(
    test_ledger: TrialLedger,
) -> None:
    with pytest.raises(TrialRecordError):
        test_ledger.debit("not-a-uuid", CAMPAIGN, epoch_id=EPOCH, **PROVENANCE)
    with pytest.raises(TrialRecordError):
        test_ledger.debit(NODE_A, CAMPAIGN, OUTCOME, CHARGES_BUDGET, ts=datetime(2026, 9, 20, 5, 0, 0), epoch_id=EPOCH, **PROVENANCE)
    assert test_ledger.count() == 0


def test_the_raw_append_still_counts_what_it_is_told(
    test_endpoint: DebitEndpoint, test_ledger: TrialLedger
) -> None:
    # Feature 86's contract is unchanged by feature 95: the raw append
    # is not idempotent and never was — two calls are two rows — because
    # idempotence is the *debit's* contract, not the log's write
    # primitive's.
    test_ledger.append(NODE_A, CAMPAIGN, OUTCOME, CHARGES_BUDGET, epoch_id=EPOCH, **PROVENANCE)
    test_ledger.append(NODE_A, CAMPAIGN, OUTCOME, CHARGES_BUDGET, epoch_id=EPOCH, **PROVENANCE)
    assert test_ledger.count() == 2


# -- The endpoint's construction -------------------------------------------------


def test_the_endpoint_refuses_something_without_a_debit_seam() -> None:
    with pytest.raises(TypeError, match="debit"):
        DebitEndpoint(object())  # type: ignore[arg-type]


def test_the_endpoint_duck_accepts_the_composed_component(
    test_database_url: str,
) -> None:
    # The factory's scan imports the member under an alias module, so
    # the composed component is structurally a TrialLedger but never the
    # same class object a direct import yields — the endpoint must take
    # it anyway (the seam is the contract, not the class identity).
    app = create_app(MEMBER_SRC, registry=Registration())
    composed = ledger_seat.ledger_component(app)
    endpoint = DebitEndpoint(composed)  # type: ignore[arg-type]
    assert endpoint.post(DebitRequest(NODE_A, CAMPAIGN, OUTCOME, CHARGES_BUDGET, epoch_id=EPOCH, **PROVENANCE)).seq == 1


def test_from_env_resolves_the_configured_ledger(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(DATABASE_URL_ENV, "sqlite:///somewhere/ledger.db")
    endpoint = DebitEndpoint.from_env()
    assert endpoint is not None
    assert endpoint.ledger.database_url == "sqlite:///somewhere/ledger.db"
    assert endpoint.route == DEBIT_ROUTE


@pytest.mark.parametrize("blank", ["", "   "])
def test_from_env_treats_blank_as_absent(
    monkeypatch: pytest.MonkeyPatch, blank: str
) -> None:
    monkeypatch.setenv(DATABASE_URL_ENV, blank)
    assert DebitEndpoint.from_env() is None


def test_from_env_reads_a_handed_environment_over_the_process_one() -> None:
    endpoint = DebitEndpoint.from_env({DATABASE_URL_ENV: "sqlite:///handed.db"})
    assert endpoint is not None
    assert endpoint.ledger.database_url == "sqlite:///handed.db"


# -- Registration, composition, seat ----------------------------------------------


def test_the_route_is_spelled_once_everywhere() -> None:
    assert DEBIT_ROUTE == "/ledger/debit"
    assert DebitEndpoint.route == DEBIT_ROUTE


def test_the_scan_registers_the_debit_component() -> None:
    registry = Registration()
    components = scan_components(MEMBER_SRC, registry=registry)
    names = [component.name for component in components]
    assert DEBIT_COMPONENT_NAME in names
    assert DEBIT_COMPONENT_NAME == "ledger-debit"
    # The ledger component itself is still exactly one registration.
    assert names.count("ledger") == 1


def test_the_composed_app_builds_the_debit_endpoint(
    test_database_url: str,
) -> None:
    app = create_app(MEMBER_SRC, registry=Registration())
    component = app.get(DEBIT_COMPONENT_NAME)
    assert component is not None
    assert callable(component.post)
    assert component.route == DEBIT_ROUTE
    assert component.ledger.database_url == test_database_url
    assert DEBIT_COMPONENT_NAME in app.order


def test_the_debit_builder_contributes_nothing_without_a_store(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(DATABASE_URL_ENV, raising=False)
    app = create_app(MEMBER_SRC, registry=Registration())
    assert app.get(DEBIT_COMPONENT_NAME) is None


def test_the_endpoint_and_the_store_compose_over_one_database(
    test_database_url: str,
) -> None:
    # One resolution, one database: the composed endpoint debits the
    # very ledger the composed "ledger" component names, so a deployment
    # can never charge one table while reading another.
    app = create_app(MEMBER_SRC, registry=Registration())
    endpoint = app.get(DEBIT_COMPONENT_NAME)
    store = app.get("ledger")
    assert endpoint.ledger.database_url == store.database_url

    response = endpoint.post(DebitRequest(NODE_A, CAMPAIGN, OUTCOME, CHARGES_BUDGET, epoch_id=EPOCH, **PROVENANCE))
    assert store.get(response.seq) == response.record


def test_the_seat_exposes_the_composed_debit_endpoint(
    test_database_url: str,
) -> None:
    assert ledger_seat.DEBIT_COMPONENT_NAME == DEBIT_COMPONENT_NAME
    app = create_app(MEMBER_SRC, registry=Registration())
    component = ledger_seat.debit_component(app)
    assert component is app.get(DEBIT_COMPONENT_NAME)
    assert callable(component.post)


def test_the_seat_reads_a_debit_component_from_an_application_it_is_handed() -> None:
    application = Application(
        components={DEBIT_COMPONENT_NAME: {"sentinel": True}},
        order=(DEBIT_COMPONENT_NAME,),
    )
    assert ledger_seat.debit_component(application) == {"sentinel": True}


def test_an_absent_debit_component_is_none_rather_than_an_error() -> None:
    assert ledger_seat.debit_component(Application()) is None
