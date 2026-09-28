"""``POST /ledger/debit`` and ``GET /ledger/k-effective`` over HTTP.

The two routes feature 95 and feature 94 expose in-process and feature 7
of additions_spec_journeys.xml serves over the wire, held to this build's
own sentence: *System serves POST /ledger/debit and GET /ledger/k-effective
as JSON, which returns 201 for an appended charge and 200 with the same
sequence number for an idempotent retry.*

Three clauses, each its own section below:

* **201 for an appended charge** — a node the ledger holds no row for
  takes the insert, and the status says so.  The body carries the
  member's own :class:`~ledger.debit.DebitResponse`: ``appended`` true and
  the ``record`` the row was read back as — its ``seq``, its stamp, its
  two identities, its outcome, its budget directive, its unit, its epoch
  and its provenance triple.
* **200 with the same sequence number for an idempotent retry** — the
  same charge arriving twice is one row, and the second POST answers the
  standing row with ``appended`` false and *the very ``seq`` the first
  POST returned*.  That equality is the feature's whole point: §6.1's
  step 11 debits even when the node fails, and §14's spot instances retry
  by ``node_id``, so a retry that minted a second number would inflate the
  one figure §8's honest counter exists to keep honest — and it would do
  it precisely where nobody is watching.  The status is derived from
  ``appended`` and nothing else, so a retry can never be answered as a
  creation.
* **the two routes are served, not 501** — before this feature landed
  ``POST /ledger/debit`` was declared in the route table (so its verb
  answered 405 and its component resolved) but carried no adapter and
  answered ``route_not_implemented``.  The tests below prove the adapter
  now serves the member's own act, and that ``GET /ledger/k-effective``
  answers feature 93's derivation — the honest per-epoch count, never a
  raw row count.

The 400 door is pinned beside them, because the split is the point: a
charge that cannot say what it is charging (an unknown outcome, a
malformed provenance term, a naive stamp, an absent epoch or directive)
is the *caller's* to repair, and it must never be confused with the
deployment refusal (a store that could not be written) that answers 503.
Every one of those travels through a different door, and a bad charge
spends no sequence number on its way out.

**One status this suite deliberately does not pin.**  A store the
deployment cannot open is answered ``503`` on the write route (the
member's own ``TrialStoreError``) and by the transport's generic internal
error on the read route, because ``TrialLedger.k_effective`` raises the
driver's own error rather than wrapping it the way its ``epoch_usage``
sibling does.  That difference is a fact about how two *store reads*
compose their own error — owned in ``packages/ledger``, outside this
member's footprint — so the read-fault test below pins only what the
transport owns: the envelope carries no stack and no path, and a failed
read is never answered with a fabricated figure.  Pinning ``500`` here
would freeze another member's defect as this route's contract.

The suite composes the real application (``create_app()``) over a
per-test sqlite store and seeds through the members' own public seams —
:func:`nullius_api.demo.seed_demo_store` for the common state and
:class:`ledger.TrialLedger` for the charges this suite writes itself —
never through a second spelling of a row a member already owns.
"""

from __future__ import annotations

import hashlib
import http.client
import json
import threading
import uuid
from dataclasses import dataclass
from typing import Any

import pytest
from nullius_api import ApiServer
from nullius_api.demo import seed_demo_store

from app.module_loader import create_app

# -- Booting the real, composed server ---------------------------------------------


class _Boot:
    """Boot one composed server per case on an ephemeral loopback port."""

    def __init__(self) -> None:
        self._servers: list[ApiServer] = []

    def __call__(self, application: Any = None) -> ApiServer:
        server = ApiServer(
            ("127.0.0.1", 0),
            application if application is not None else create_app(),
        )
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self._servers.append(server)
        return server

    def shutdown(self) -> None:
        for server in self._servers:
            server.shutdown()
            server.server_close()


@pytest.fixture
def boot():
    runner = _Boot()
    yield runner
    runner.shutdown()


def _post(server: ApiServer, path: str, body: Any) -> tuple[int, dict[str, str], Any]:
    connection = http.client.HTTPConnection(
        "127.0.0.1", server.server_address[1], timeout=10
    )
    try:
        connection.request(
            "POST",
            path,
            json.dumps(body).encode("utf-8"),
            {"Content-Type": "application/json"},
        )
        response = connection.getresponse()
        raw = response.read().decode("utf-8")
        headers = {name.lower(): value for name, value in response.getheaders()}
        return response.status, headers, (json.loads(raw) if raw else None)
    finally:
        connection.close()


def _get(server: ApiServer, path: str) -> tuple[int, dict[str, str], Any]:
    connection = http.client.HTTPConnection(
        "127.0.0.1", server.server_address[1], timeout=10
    )
    try:
        connection.request("GET", path)
        response = connection.getresponse()
        raw = response.read().decode("utf-8")
        headers = {name.lower(): value for name, value in response.getheaders()}
        return response.status, headers, (json.loads(raw) if raw else None)
    finally:
        connection.close()


@pytest.fixture
def seeded(test_database_url: str):
    """The demo store: three sealed epochs, a promoted node with two
    forward observations, and two trial-ledger charges — one budget-
    charging, one a null node's."""
    return seed_demo_store(test_database_url), test_database_url


# -- The charge document ------------------------------------------------------------

#: The provenance triple this suite's own charges carry — sha256 of fixed
#: labels, in the canonical lowercase-hex spelling
#: :func:`ledger.provenance.validated_provenance_hash` and the ``CHAR(64)``
#: columns both require.  Fixed rather than fresh, so a failure names a
#: document a reader can reproduce.
_EVALUATOR_HASH = hashlib.sha256(b"api-suite-evaluator").hexdigest()
_SNAPSHOT_HASH = hashlib.sha256(b"api-suite-snapshot").hexdigest()
_COST_MODEL_HASH = hashlib.sha256(b"api-suite-cost-model").hexdigest()


def _charge(**overrides: Any) -> dict[str, Any]:
    """One full charge document — every term feature 95 requires, so an
    override is the *only* thing a test's body differs by."""
    document: dict[str, Any] = {
        "node_id": str(uuid.uuid4()),
        "campaign_id": str(uuid.uuid4()),
        "outcome": "ok",
        "charges_budget": True,
        "charge_units": 1.0,
        "epoch_id": "epoch-api-suite",
        "evaluator_hash": _EVALUATOR_HASH,
        "snapshot_hash": _SNAPSHOT_HASH,
        "cost_model_hash": _COST_MODEL_HASH,
    }
    document.update(overrides)
    return document


# -- 201 for an appended charge -----------------------------------------------------


def test_a_fresh_charge_is_appended_and_answered_201(boot) -> None:
    """The first clause: a node the ledger holds no row for takes the
    insert, the status says so, and the body is the member's own record —
    every term the caller stated read back off the row it landed in."""
    document = _charge()
    server = boot(create_app())
    status, headers, body = _post(server, "/ledger/debit", document)

    assert status == 201
    assert headers["content-type"] == "application/json"
    assert body["appended"] is True
    record = body["record"]
    assert record["seq"] == 1  # the ledger's first charge
    assert record["node_id"] == document["node_id"]
    assert record["campaign_id"] == document["campaign_id"]
    assert record["outcome"] == "ok"
    assert record["charges_budget"] is True
    assert record["charge_units"] == 1.0
    assert record["epoch_id"] == "epoch-api-suite"
    assert record["evaluator_hash"] == _EVALUATOR_HASH
    assert record["snapshot_hash"] == _SNAPSHOT_HASH
    assert record["cost_model_hash"] == _COST_MODEL_HASH
    # The stamp is the store's own clock, aware-UTC, ISO-8601 on the wire
    # — the one textual instant spelling every member's records carry.
    assert record["ts"].endswith("+00:00")


def test_an_appended_charge_really_lands_in_the_ledger(
    boot, test_database_url: str
) -> None:
    """The status is not the only testimony: the row the answer names is
    in the table the store reads, and its sequence is the one the body
    carried — never a number minted for the response."""
    import ledger

    document = _charge()
    server = boot(create_app())
    _, _, body = _post(server, "/ledger/debit", document)

    trial_ledger = ledger.TrialLedger(test_database_url)
    stored = trial_ledger.get(body["record"]["seq"])
    assert stored is not None
    assert stored.node_id == document["node_id"]
    assert stored.seq == body["record"]["seq"]
    assert trial_ledger.count() == 1


def test_a_charge_carries_the_failure_outcome_it_ended_with(boot) -> None:
    """§6.1's step 11 debits even when the node fails, so the outcome is
    required rather than defaulted — and a charged failure is as real a
    row as a charged success."""
    document = _charge(outcome="tripwire_fail")
    server = boot(create_app())
    status, _, body = _post(server, "/ledger/debit", document)
    assert status == 201
    assert body["record"]["outcome"] == "tripwire_fail"


def test_a_null_nodes_charge_is_appended_and_is_honestly_recorded(boot) -> None:
    """A null node's charge is booked — the ledger is append-only and the
    node was evaluated — while its directive says it spent no statistical
    budget.  The two facts ride together, which is exactly why the
    directive had to cross §7.2's barrier as an opaque bool."""
    document = _charge(charges_budget=False)
    server = boot(create_app())
    status, _, body = _post(server, "/ledger/debit", document)
    assert status == 201
    assert body["record"]["charges_budget"] is False


def test_the_charge_unit_defaults_to_one_when_the_body_omits_it(boot) -> None:
    """The one term on this body with an honest presumption: §8's own
    ``DEFAULT 1.0`` — an ordinary evaluation costs one unit, and a
    cross-validated one states its folds' count itself."""
    document = _charge()
    document.pop("charge_units")
    server = boot(create_app())
    status, _, body = _post(server, "/ledger/debit", document)
    assert status == 201
    assert body["record"]["charge_units"] == 1.0


def test_a_cross_validated_charges_own_unit_is_relayed_not_clamped(boot) -> None:
    """A charge that costs its folds' count says so, and the transport
    neither clamps, rounds nor re-derives it — the figure on the wire is
    the figure the caller stated and the row holds."""
    document = _charge(charge_units=5.0)
    server = boot(create_app())
    status, _, body = _post(server, "/ledger/debit", document)
    assert status == 201
    assert body["record"]["charge_units"] == 5.0


def test_a_replay_charge_stamps_the_instant_it_reproduces(boot) -> None:
    """The ``ts`` the replay path supplies is the instant the charge
    happened, not the instant it re-ran; the store stamps with it and the
    body answers it back."""
    document = _charge(ts="2026-05-01T09:30:00+00:00")
    server = boot(create_app())
    status, _, body = _post(server, "/ledger/debit", document)
    assert status == 201
    assert body["record"]["ts"].startswith("2026-05-01T09:30:00")


# -- 200 with the same sequence number for an idempotent retry ----------------------


def test_a_retry_answers_200_with_the_same_sequence_number(boot) -> None:
    """The flagship clause.  One charge posted twice is one row; the
    second POST answers ``appended`` false and *the very sequence the
    first returned*, so the caller's account of what was spent and the
    ledger's never diverge however many times the retry fires."""
    document = _charge()
    server = boot(create_app())

    first_status, _, first = _post(server, "/ledger/debit", document)
    second_status, _, second = _post(server, "/ledger/debit", document)

    assert first_status == 201
    assert second_status == 200
    assert first["appended"] is True
    assert second["appended"] is False
    assert second["record"]["seq"] == first["record"]["seq"]


def test_a_retry_appends_nothing_at_all(boot, test_database_url: str) -> None:
    """Idempotence is a fact about the table, not about the status: after
    the retry the ledger still holds one row, and the next node's first
    charge draws the *very next* number — a skipped charge spends none."""
    import ledger

    document = _charge()
    server = boot(create_app())
    _post(server, "/ledger/debit", document)
    _post(server, "/ledger/debit", document)

    trial_ledger = ledger.TrialLedger(test_database_url)
    assert trial_ledger.count() == 1

    other = _charge()
    status, _, body = _post(server, "/ledger/debit", other)
    assert status == 201
    assert body["record"]["seq"] == 2


def test_a_retry_is_answered_by_the_prior_row_not_by_a_restatement(boot) -> None:
    """On a retry nothing is written — not the stamp, not the outcome —
    so the row that comes back is the row as first written.  A retry
    whose body states a *different* outcome is silently the loser of that
    rule, which is append-only accounting: a charge is never restated."""
    document = _charge(outcome="error")
    server = boot(create_app())
    _, _, first = _post(server, "/ledger/debit", document)
    _, _, second = _post(
        server, "/ledger/debit", {**document, "outcome": "timeout"}
    )
    assert second["record"]["outcome"] == "error"
    assert second["record"]["ts"] == first["record"]["ts"]


def test_many_retries_all_answer_200_with_the_one_sequence(boot) -> None:
    """§14's spot instances retry until one of them lands.  However many
    times the charge is posted, every answer but the first is 200 and
    every answer names one sequence number — the first one."""
    document = _charge()
    server = boot(create_app())
    answers = [_post(server, "/ledger/debit", document) for _ in range(4)]
    assert [status for status, _, _ in answers] == [201, 200, 200, 200]
    sequences = {body["record"]["seq"] for _, _, body in answers}
    assert sequences == {1}


def test_two_different_nodes_are_two_charges(boot) -> None:
    """The key is the node, and only the node: two evaluations are two
    rows with two sequences, however alike their documents otherwise
    are."""
    first_document = _charge()
    second_document = _charge(campaign_id=first_document["campaign_id"])
    server = boot(create_app())
    first_status, _, first = _post(server, "/ledger/debit", first_document)
    second_status, _, second = _post(server, "/ledger/debit", second_document)
    assert (first_status, second_status) == (201, 201)
    assert first["record"]["seq"] != second["record"]["seq"]


def test_a_retry_of_a_row_written_before_this_deployment_is_still_200(
    boot, test_database_url: str
) -> None:
    """Idempotence lives in the table, not in the endpoint's memory: a
    row a previous process appended is answered by exactly the row
    :meth:`ledger.store.TrialLedger.debit` finds standing."""
    import ledger

    document = _charge()
    trial_ledger = ledger.TrialLedger(test_database_url)
    prior, appended = trial_ledger.debit(
        document["node_id"],
        document["campaign_id"],
        outcome="ok",
        charges_budget=True,
        charge_units=1.0,
        epoch_id=document["epoch_id"],
        evaluator_hash=_EVALUATOR_HASH,
        snapshot_hash=_SNAPSHOT_HASH,
        cost_model_hash=_COST_MODEL_HASH,
    )
    assert appended is True

    server = boot(create_app())
    status, _, body = _post(server, "/ledger/debit", document)
    assert status == 200
    assert body["appended"] is False
    assert body["record"]["seq"] == prior.seq


# -- The 400 door: a charge that cannot say what it is charging ---------------------


@pytest.mark.parametrize(
    "overrides",
    [
        {"outcome": "exploded"},  # outside feature 91's four names
        {"outcome": None},  # absent — a charge no audit can classify
        {"charges_budget": 1},  # not a genuine bool (feature 90)
        {"charges_budget": None},  # absent — the directive is supplied
        {"charge_units": 0},  # not a positive real (feature 89)
        {"charge_units": -2.0},
        {"epoch_id": None},  # feature 88: a charge must name its holdout
        {"epoch_id": "   "},
        {"evaluator_hash": "not-a-digest"},  # feature 87's triple
        {"evaluator_hash": None},
        {"snapshot_hash": "ab" * 16},
        {"cost_model_hash": None},
        {"node_id": "not-a-uuid"},
        {"campaign_id": None},
        {"ts": "2026-05-01T09:30:00"},  # naive — no offset to compare with
        {"ts": "yesterday"},
    ],
)
def test_a_charge_that_cannot_say_what_it_is_charging_is_refused_400(
    boot, overrides: dict[str, Any]
) -> None:
    """Every term feature 95 requires is required *at the wire*: a body
    missing one, or stating one that fails its own contract, is the
    caller's to repair.  The refusal is the transport's own 400 — never
    the member-refusal 503, which would tell a caller to escalate a
    deployment that is answering correctly."""
    from nullius_api import MALFORMED_REQUEST_CLASS

    server = boot(create_app())
    status, _, body = _post(server, "/ledger/debit", _charge(**overrides))
    assert status == 400
    assert body["error"]["code"] == "malformed_body"
    assert body["error"]["class"] == MALFORMED_REQUEST_CLASS
    # The member's own sentence naming the offending term and the one
    # repair is published verbatim — it is the half a caller acts on.
    assert body["error"]["message"]


def test_a_refused_charge_spends_no_sequence_number(
    boot, test_database_url: str
) -> None:
    """A malformed body never reaches the store, so it costs the ledger
    nothing: the next honest charge still draws sequence 1."""
    import ledger

    server = boot(create_app())
    status, _, _ = _post(server, "/ledger/debit", _charge(outcome="exploded"))
    assert status == 400

    assert ledger.TrialLedger(test_database_url).count() == 0
    _, _, body = _post(server, "/ledger/debit", _charge())
    assert body["record"]["seq"] == 1


def test_a_body_that_is_not_a_json_object_is_refused_400(boot) -> None:
    """The reader's own door, ahead of any route: bytes that are not the
    JSON object the route reads are refused before the store is
    consulted."""
    server = boot(create_app())
    connection = http.client.HTTPConnection(
        "127.0.0.1", server.server_address[1], timeout=10
    )
    try:
        connection.request(
            "POST",
            "/ledger/debit",
            b"[1, 2, 3]",
            {"Content-Type": "application/json"},
        )
        response = connection.getresponse()
        body = json.loads(response.read().decode("utf-8"))
    finally:
        connection.close()
    assert response.status == 400
    assert body["error"]["code"] == "malformed_body"


def test_an_empty_body_is_a_charge_that_states_nothing(boot) -> None:
    """No body at all reaches the adapter as ``None``, and the member's
    constructor refuses the document it then cannot read — a 400 naming
    the first missing term, not a 500 over a ``None``."""
    server = boot(create_app())
    connection = http.client.HTTPConnection(
        "127.0.0.1", server.server_address[1], timeout=10
    )
    try:
        connection.request("POST", "/ledger/debit")
        response = connection.getresponse()
        body = json.loads(response.read().decode("utf-8"))
    finally:
        connection.close()
    assert response.status == 400
    assert body["error"]["class"] == "MalformedRequestError"


# -- The store's refusals are the deployment's, not the caller's --------------------


def test_the_unconfigured_store_answers_503(boot, monkeypatch) -> None:
    """No ``DATABASE_URL`` composes no ledger component, so the route has
    no store to append to.  That is a different fact from a charge that
    could not say what it was — and it must not be reported as one."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    server = boot(create_app())
    status, _, body = _post(server, "/ledger/debit", _charge())
    assert status == 503
    assert body["error"]["code"] == "component_unconfigured"
    assert "ledger-debit" in body["error"]["message"]


def test_a_store_that_cannot_be_written_answers_the_member_refusal(
    boot, monkeypatch, tmp_path
) -> None:
    """A configured store whose write fails raises the member's own
    :class:`~ledger.errors.TrialStoreError` — a 503 carrying the member's
    message and the member's class, never the transport's 400.

    The deployment here is a database path that is a *directory*: sqlite
    cannot open it, so the charge cannot land, which is exactly the fault
    feature 86 exists to make un-swallowable — a debit that silently did
    not persist would be an evaluation that spent a hypothesis while the
    honest counter looked away."""
    blocked = tmp_path / "a-directory-not-a-database"
    blocked.mkdir()
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{blocked}")

    server = boot(create_app())
    status, _, body = _post(server, "/ledger/debit", _charge())
    assert status == 503
    assert body["error"]["code"] == "member_refusal"
    assert body["error"]["class"] == "TrialStoreError"


# -- The status is read off the member's flag, never invented -----------------------


@dataclass(frozen=True)
class _FakeRecord:
    """A record shaped like the member's — the fields the wire spells.

    A dataclass, because the codec spells a response by its fields: a
    bare object would be refused by the encoder and answered as an
    internal error, which is a different test entirely.
    """

    seq: int
    ts: str
    node_id: str
    campaign_id: str
    outcome: str
    charges_budget: bool
    charge_units: float
    epoch_id: str


@dataclass(frozen=True)
class _FakeResponse:
    """A response shaped like the member's: the flag, and the record.

    Used only by :class:`_UnreadableEndpoint` — the composition-fault
    case — because it is *not* the member's own response class and
    therefore may carry an ``appended`` that is not a boolean.
    """

    appended: Any
    record: Any


class _UnreadableEndpoint:
    """An endpoint answering a response whose ``appended`` is not a bool.

    A component that already speaks ``post`` passes through
    :func:`~nullius_api.routes.resolve_routes` unwrapped, which is how a
    response the transport cannot read can be driven without a member
    that would never compose one.
    """

    route = "/ledger/debit"

    def __init__(self, answer: Any) -> None:
        self._answer = answer

    def post(self, request):  # pragma: no cover - the answer is the point
        return self._answer


class _RefusingEndpoint:
    """An endpoint raising what a served member's own store would raise."""

    route = "/ledger/debit"

    def __init__(self, refusal: BaseException) -> None:
        self._refusal = refusal

    def post(self, request):  # pragma: no cover - the refusal is the point
        raise self._refusal


def _boot_with_ledger_component(boot, component: Any) -> ApiServer:
    from app.module_loader import Application

    return boot(
        Application(components={"ledger-debit": component}, order=("ledger-debit",))
    )


def test_an_unreadable_response_is_a_composition_fault_not_a_status(boot) -> None:
    """A response whose ``appended`` is not a boolean is refused
    internally — the transport will not invent a 201 for a record it
    cannot read, because that would claim a charge was written that may
    not have been — and the body stays the generic internal error with
    nothing of the record echoed."""
    server = _boot_with_ledger_component(
        boot, _UnreadableEndpoint(_FakeResponse(appended="yes", record=None))
    )
    status, _, body = _post(server, "/ledger/debit", _charge())
    assert status == 500
    assert body["error"]["code"] == "internal_error"
    assert "yes" not in json.dumps(body)


def test_the_member_refusal_door_carries_the_members_own_class(boot) -> None:
    """A refusal raised by the served member's code is answered with the
    member's own class — ``type(exc).__name__``, the very name the
    member's traceback would give — and never with one the transport
    invented."""
    refusal = type("TrialStoreError", (Exception,), {"__module__": "ledger.errors"})(
        "trial_store_error: the ledger could not be written; the repair"
    )
    server = _boot_with_ledger_component(boot, _RefusingEndpoint(refusal))
    status, _, body = _post(server, "/ledger/debit", _charge())
    assert status == 503
    assert body["error"]["code"] == "member_refusal"
    assert body["error"]["class"] == "TrialStoreError"
    assert body["error"]["message"].startswith("trial_store_error")


# -- GET /ledger/k-effective: the deflation input -----------------------------------


def test_the_k_effective_route_answers_the_derivation_per_epoch(
    boot, seeded
) -> None:
    """Feature 94's route, over the demo store: one pair per observed
    epoch, the un-named epoch first then ascending spelling, each count
    the trials that epoch holds whose directive is true.

    The demo's two charges are one budget-charging real trial and one
    null node's, so the *whole point* of feature 93 is visible here: the
    ledger holds two rows and ``K_effective`` is one."""
    report, _url = seeded
    server = boot(create_app())
    status, headers, body = _get(server, "/ledger/k-effective")

    assert status == 200
    assert headers["content-type"] == "application/json"
    counts = {epoch: count for epoch, count in body["view"]["counts"]}
    assert counts[report.epoch_ids[0]] == 1
    # The null node's epoch is *reported*, at 0 — a fact about the world
    # the deflation term must be told rather than left to infer from an
    # absent key.
    assert counts[report.epoch_ids[1]] == 0


def test_the_deflated_count_is_not_the_row_count(boot, seeded) -> None:
    """The route answers feature 93's derivation, never the plain row
    count: the demo store holds two trial rows and answers
    ``K_effective`` one, because a null node is charged but never counted.

    A route that fell back to the row count would inflate §10.3's
    deflation input by every null node a campaign ran — silently, under a
    route name that promises the opposite."""
    _report, url = seeded
    import ledger

    assert ledger.TrialLedger(url).count() == 2
    server = boot(create_app())
    _, _, body = _get(server, "/ledger/k-effective")
    total = sum(count for _epoch, count in body["view"]["counts"])
    assert total == 1


def test_an_empty_ledger_answers_empty_counts_never_a_fabricated_zero(
    boot, test_database_url: str
) -> None:
    """An empty ledger has observed no epoch at all, so the honest answer
    is an empty breakdown — not ``0`` under an epoch nobody named, and
    certainly not a fabricated figure.  The same law the members' own
    empty stores hold, passed straight through the transport."""
    server = boot(create_app())
    status, _, body = _get(server, "/ledger/k-effective")
    assert status == 200
    assert body == {"view": {"counts": []}}


def test_a_charge_posted_over_http_moves_the_k_effective_answer(boot) -> None:
    """The two routes are one ledger, and they agree because neither
    caches: a charge appended through the POST is counted by the very
    next GET, in the same process, with no restart and no refresh."""
    server = boot(create_app())
    _, _, before = _get(server, "/ledger/k-effective")
    assert before["view"]["counts"] == []

    document = _charge(epoch_id="epoch-live")
    _post(server, "/ledger/debit", document)

    _, _, after = _get(server, "/ledger/k-effective")
    assert dict(after["view"]["counts"]) == {"epoch-live": 1}


def test_a_null_charge_moves_no_count_but_still_is_booked(boot) -> None:
    """Both halves at once: the null node's charge is appended (201, a
    row in the append-only ledger) and contributes *nothing* to
    ``K_effective`` — while its epoch is reported at ``0`` rather than
    omitted."""
    server = boot(create_app())
    document = _charge(charges_budget=False, epoch_id="epoch-null")
    status, _, _ = _post(server, "/ledger/debit", document)
    assert status == 201

    _, _, body = _get(server, "/ledger/k-effective")
    assert dict(body["view"]["counts"]) == {"epoch-null": 0}


def test_the_k_effective_route_answers_the_members_own_derivation(boot, seeded) -> None:
    """The figure on the wire is the store's own derivation, not a second
    computation: the pairs the route reports are the pairs
    :meth:`ledger.store.TrialLedger.k_effective` answers, epoch for
    epoch."""
    _report, url = seeded
    import ledger

    derived = dict(ledger.TrialLedger(url).k_effective().counts)
    server = boot(create_app())
    _, _, body = _get(server, "/ledger/k-effective")
    assert {epoch: count for epoch, count in body["view"]["counts"]} == derived


def test_the_unconfigured_store_answers_503_on_the_read_too(
    boot, monkeypatch
) -> None:
    """The read degrades the same way the write does: no ``DATABASE_URL``
    composes no endpoint, and the route says so rather than answering a
    deflation input drawn from nowhere."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    server = boot(create_app())
    status, _, body = _get(server, "/ledger/k-effective")
    assert status == 503
    assert body["error"]["code"] == "component_unconfigured"
    assert "ledger-k-effective" in body["error"]["message"]


# -- The routes are served, not 501 -------------------------------------------------


def test_the_debit_route_is_served_not_501(boot) -> None:
    """Before this feature landed the route was declared in the table but
    carried no adapter and answered ``route_not_implemented``; the tests
    above prove it now serves the member's own act."""
    server = boot(create_app())
    status, _, body = _post(server, "/ledger/debit", _charge())
    assert status != 501
    assert body.get("error", {}).get("code") != "route_not_implemented"


def test_the_k_effective_route_is_served_not_501(boot) -> None:
    server = boot(create_app())
    status, _, body = _get(server, "/ledger/k-effective")
    assert status == 200
    assert "view" in body


def test_a_wrong_verb_answers_405_with_an_allow_header(boot) -> None:
    """Each path serves its own verb alone; the other is the transport's
    own refusal, stated with the verb the route does answer."""
    server = boot(create_app())
    status, headers, body = _get(server, "/ledger/debit")
    assert status == 405
    assert headers["allow"] == "POST"
    assert body["error"]["code"] == "method_not_allowed"

    status, headers, body = _post(server, "/ledger/k-effective", {})
    assert status == 405
    assert headers["allow"] == "GET"


# -- The envelope's own laws --------------------------------------------------------


@pytest.mark.parametrize("status_code", [200, 201, 400])
def test_no_body_carries_a_traceback_or_a_filesystem_path(
    boot, tmp_path, status_code: int
) -> None:
    """The envelope's last law over every answer this route gives: no
    body names a stack or a path, whichever status it wears.  The test
    run's own temporary directory is the leash — the store URL this
    suite's fixture points ``DATABASE_URL`` at lives under it, so a
    leaked path would name something real."""
    document = _charge(outcome="ok" if status_code != 400 else "exploded")
    server = boot(create_app())
    if status_code == 200:
        _post(server, "/ledger/debit", document)  # the row the retry answers
    status, _, answer = _post(server, "/ledger/debit", document)
    assert status == status_code
    text = json.dumps(answer)
    assert "Traceback" not in text
    assert str(tmp_path) not in text
    assert ".py" not in text
    assert ".db" not in text


def test_the_store_faults_body_leaks_no_traceback_or_path(
    boot, monkeypatch, tmp_path
) -> None:
    """The 503 door's own body — the one refusal that arrives carrying a
    store's composer's words, and therefore the one most likely to name
    where it looked.  It must not."""
    blocked = tmp_path / "a-directory-not-a-database"
    blocked.mkdir()
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{blocked}")
    server = boot(create_app())
    status, _, answer = _post(server, "/ledger/debit", _charge())
    assert status == 503
    text = json.dumps(answer)
    assert "Traceback" not in text
    assert ".py" not in text
    # The store's own sentence names the URL it could not open — and the
    # transport publishes the configuration, never the deployment's
    # directory layout.
    assert str(blocked) not in text


def test_the_read_faults_body_leaks_no_traceback_or_path(
    boot, monkeypatch, tmp_path
) -> None:
    """The same law over the other verb: a store this deployment cannot
    open must not have its directory layout published on the *read*
    route either.

    The status is deliberately not pinned here.  The write path raises
    the member's own ``TrialStoreError`` and so answers the member's 503;
    the read path reaches the store through ``k_effective``, whose raw
    ``sqlite3.OperationalError`` the transport cannot attribute to a
    member and therefore answers as its generic internal error.  Which
    status each path takes is the *member's* to settle — it is a
    difference in how two store reads compose their own error, owned in
    ``packages/ledger`` and outside this member's footprint.  What the
    transport owns, and what this test pins, is the envelope: whatever
    the status, the body carries no stack and no path, and the failure is
    never answered with a fabricated figure."""
    blocked = tmp_path / "a-directory-not-a-database"
    blocked.mkdir()
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{blocked}")
    server = boot(create_app())
    status, _, answer = _get(server, "/ledger/k-effective")

    assert status >= 400, "a store this deployment cannot open is not a success"
    text = json.dumps(answer)
    assert "Traceback" not in text
    assert ".py" not in text
    assert str(blocked) not in text
    # No fabricated figure: the failed read is refused, never answered as
    # an empty breakdown or a zero the ledger never stated.  The body is
    # the error envelope and carries no ``view`` at all — not an empty
    # one, and not a null one, either of which a caller could read as a
    # ledger that holds nothing rather than a ledger that could not be
    # read.
    assert "view" not in answer
    assert answer["error"]["code"] in {"internal_error", "member_refusal"}


def test_the_retry_and_the_append_are_told_apart_by_the_flag_not_the_status_alone(
    boot,
) -> None:
    """A caller that reads only the status still learns which call wrote
    the row, because ``appended`` is the store's own finding passed
    through — the status is derived from it and never the other way
    round."""
    document = _charge()
    server = boot(create_app())
    _, _, first = _post(server, "/ledger/debit", document)
    _, _, second = _post(server, "/ledger/debit", document)
    assert (first["appended"], second["appended"]) == (True, False)
    # And the whole record body is identical between the two — one row,
    # answered twice.
    assert first["record"] == second["record"]
