"""The journeys, end to end, over one booted server against the demo store.

additions_spec_journeys.xml feature 17 — *System passes an end-to-end test
that boots the HTTP server on an ephemeral port against a seeded demo store
and asserts each route returns its documented HTTP status code for success,
retry, absence, refusal, missing token and out-of-scope token, and that no
response body contains a traceback.*

This is the capstone of the API journeys (docs/user-journeys/J08–J14): where
every earlier suite holds *one* route over *its own* fixture — the metrics
suites over an empty store, the ledger and promotion suites over a seeded
one, the target suite over a sealed sidecar, the token-gate suite over
fakes — this one boots the *whole* composition at once, over the *one* store
:func:`nullius_api.demo.seed_demo_store` seeds, and reads back the status
each journey's document promises for the state that store holds. It is the
difference between "each route works when exercised alone" and "the server
that serves all ten routes at once answers each of them as documented over
the deployment an operator actually runs".

**One server, one store, one seal.** The fixture below seeds the demo store
into this test's isolated database, points ``NULL_SIDECAR_PATH`` at a
throwaway file and seals one real node and one null node into it (the state
``POST /target`` answers from), composes the application the factory builds,
binds the demo's in-memory paper execution engine to ``POST /risk/halt`` the
way ``python -m nullius_api`` binds it (``NULLIUS_EXECUTION_ENGINE`` →
``nullius_api.demo:PAPER_ENGINE``), and boots that single composition on an
ephemeral loopback port. Every test below talks to that one server, so the
statuses it asserts are the statuses of *this* deployment, not of a hand-
built stand-in.

The states the demo store holds fix which status each route can show here,
and that is the point rather than a limitation: a route's *success* is read
against a store that has something in it (the three metrics populated, a
charge appended, a curve observed), its *retry* against a row the seed or a
prior POST already wrote (the demo node already promoted, a charge already
appended), its *absence* against a node the sealed sidecar does not know, its
*refusal* against a known node whose series supply the deployment has not
wired. ``POST /target``'s 200 — which needs a wired supply — is deliberately
out of reach of a bare demo and is held, over a wired supply, by
``test_target_route``; this suite holds what the demo store can state.

Nothing this test seeds is a second spelling of a row a member owns: the
store is seeded through the members' own public stores (the demo seed), the
sidecar through :class:`nulloracle.NullAssignment`, and the only rows this
test writes itself are the idempotent-retry rows a *prior POST* writes — the
very act each retry documents.
"""

from __future__ import annotations

import hashlib
import http.client
import json
import sqlite3
import threading
import uuid
from dataclasses import dataclass
from typing import Any
from urllib.parse import unquote, urlparse

import pytest
from conftest import TEST_TOKENS, token_for
from nullius_api import (
    API_ROUTES,
    API_SCOPES,
    ApiServer,
    resolve_execution_engine,
)
from nullius_api.demo import PAPER_ENGINE, seed_demo_store
from nullius_api.server import TARGET_UNKNOWN_NODE_CLASS

from app.module_loader import create_app


def _sqlite_path(database_url: str) -> str:
    """Translate ``sqlite:///…`` the same way every store in this workspace
    does — restated here rather than imported, because a caller outside the
    member never reaches into its private helpers."""
    return unquote(urlparse(database_url).path).removeprefix("/")


def _insert_node(url: str, *, campaign_id: str) -> str:
    """A ``node`` row the registry can reference — the same shape
    :mod:`nullius_api.demo` inserts, for a node this suite registers on its
    own rather than through the demo seed's single fixed identity.

    The parent row is a fixture because it is not any store's job to write
    (the demo seed inserts it directly for the same reason): a registration
    names a node and an epoch, and both must stand before the row can.
    """
    node_id = str(uuid.uuid4())
    connection = sqlite3.connect(_sqlite_path(url))
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        with connection:
            connection.execute(
                "INSERT INTO node "
                "(id, campaign_id, theme_root, depth, evaluator_hash, "
                "snapshot_hash, cost_model_hash) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    node_id,
                    campaign_id,
                    "macro",
                    0,
                    hashlib.sha256(b"journey-e2e-evaluator").hexdigest(),
                    hashlib.sha256(b"journey-e2e-snapshot").hexdigest(),
                    hashlib.sha256(b"journey-e2e-cost-model").hexdigest(),
                ),
            )
    finally:
        connection.close()
    return node_id

# -- The one deployment under test --------------------------------------------------

_DEMO_CRITERIA = {
    "theta": 0.3,
    "alpha": 0.05,
    "max_fdr_deploy": 0.25,
    "min_worlds": 50,
    "min_coverage_strata": 3,
    "min_forward_days": 90,
}

#: The provenance triple this suite's own charges carry — sha256 of fixed
#: labels, in the canonical lowercase-hex spelling the ``CHAR(64)`` columns
#: require. Fixed rather than fresh, so a failure names a document a reader
#: can reproduce.
_EVALUATOR_HASH = hashlib.sha256(b"journey-e2e-evaluator").hexdigest()
_SNAPSHOT_HASH = hashlib.sha256(b"journey-e2e-snapshot").hexdigest()
_COST_MODEL_HASH = hashlib.sha256(b"journey-e2e-cost-model").hexdigest()


@dataclass(frozen=True)
class _Deployment:
    """The whole thing this suite talks to: the booted server and the facts
    about the world it was started against."""

    server: ApiServer
    report: Any
    database_url: str
    real_node: str
    null_node: str


def _assignment(node_id: str, *, is_null: bool):
    """One §7.1 assignment, built through the member's own record."""
    import nulloracle

    return nulloracle.NullAssignment(
        node_id=node_id,
        is_null=is_null,
        perm_seed=1 if is_null else 0,
        block_days=1,
    )


def _charge(node_id: str, **overrides: dict[str, Any]) -> dict[str, Any]:
    """One full debit document — every term feature 95 requires, so an
    override is the *only* thing a test's body differs by."""
    document: dict[str, Any] = {
        "node_id": node_id,
        "campaign_id": str(uuid.uuid4()),
        "outcome": "ok",
        "charges_budget": True,
        "charge_units": 1.0,
        "epoch_id": "epoch-journey-e2e",
        "evaluator_hash": _EVALUATOR_HASH,
        "snapshot_hash": _SNAPSHOT_HASH,
        "cost_model_hash": _COST_MODEL_HASH,
    }
    document.update(overrides)
    return document


def _ask_body(node_id: str, **overrides: Any) -> dict[str, Any]:
    """§7.2's six-term body for one node, with any term overridden."""
    body: dict[str, Any] = {
        "node_id": node_id,
        "campaign_id": str(uuid.uuid4()),
        "depth": 2,
        "horizon": 5,
        "symbols": ["BTCUSDT", "ETHUSDT"],
        "date_range": ["2026-01-01", "2026-02-20"],
    }
    body.update(overrides)
    return body


@pytest.fixture
def deployment(test_database_url: str, tmp_path, monkeypatch) -> _Deployment:
    """Seed the demo store, seal a sidecar, bind the paper engine, and boot
    the one composed server every test below talks to.

    The order is the deployment's own: the sidecar location is named in the
    environment *before* the application composes (the nulloracle component
    resolves its store from that variable at composition time), the store is
    seeded before anything reads it, the sidecar is sealed through the very
    component the route serves (so the seal and the serve are one world), and
    the engine is bound the way the entrypoint binds it — resolved from the
    ``nullius_api.demo:PAPER_ENGINE`` module:attribute path — so this test
    exercises the documented binding rather than a hand-held instance.
    """
    monkeypatch.setenv("NULL_SIDECAR_PATH", str(tmp_path / "null" / "sidecar.enc"))
    monkeypatch.setenv("NULL_SIDECAR_KEY_REF", "hex:" + "0f" * 32)
    monkeypatch.delenv("NULL_SIDECAR_SERVICE_ACCOUNT", raising=False)

    report = seed_demo_store(test_database_url)

    application = create_app()
    sidecar = application.get("nulloracle")
    real, null = str(uuid.uuid4()), str(uuid.uuid4())
    sidecar.write(
        [
            _assignment(real, is_null=False),
            _assignment(null, is_null=True),
        ]
    )

    engine = resolve_execution_engine("nullius_api.demo:PAPER_ENGINE")
    assert engine is PAPER_ENGINE  # the documented path resolves to the demo engine

    server = ApiServer(
        ("127.0.0.1", 0),
        application,
        TEST_TOKENS,
        execution_engine=engine,
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield _Deployment(
            server=server,
            report=report,
            database_url=test_database_url,
            real_node=real,
            null_node=null,
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


# -- One request, returning everything the assertions need --------------------------


@dataclass(frozen=True)
class _Answer:
    """A response, with its raw text preserved: the no-traceback law is
    asserted over the bytes a caller receives, not over a re-encoding."""

    status: int
    headers: dict[str, str]
    body: Any
    text: str


def _request(
    deployment: _Deployment,
    method: str,
    path: str,
    *,
    body: Any = None,
    scope: str | None,
) -> _Answer:
    """One HTTP request to the booted server, presenting ``scope``'s token
    (``None`` for no header) and returning status, headers, parsed body and
    the raw text."""
    headers: dict[str, str] = {}
    payload: bytes | None = None
    if scope is not None:
        headers["Authorization"] = f"Bearer {token_for(scope)}"
    if body is not None:
        headers["Content-Type"] = "application/json"
        payload = json.dumps(body).encode("utf-8")
    connection = http.client.HTTPConnection(
        "127.0.0.1", deployment.server.server_address[1], timeout=10
    )
    try:
        connection.request(method, path, payload, headers)
        response = connection.getresponse()
        raw = response.read().decode("utf-8")
        answer_headers = {
            name.lower(): value for name, value in response.getheaders()
        }
        parsed: Any = json.loads(raw) if raw else None
        return _Answer(response.status, answer_headers, parsed, raw)
    finally:
        connection.close()


def _get(deployment: _Deployment, path: str, scope: str) -> _Answer:
    """One authenticated GET under ``scope``."""
    return _request(deployment, "GET", path, scope=scope)


def _post(deployment: _Deployment, path: str, body: Any, scope: str) -> _Answer:
    """One authenticated POST under ``scope``."""
    return _request(deployment, "POST", path, body=body, scope=scope)


def _assert_no_traceback(answer: _Answer) -> None:
    """The envelope's own law, over a body this suite received: an operator
    reads these, and a stack, a ``.py`` frame or a filesystem path is
    neither a repair nor something to publish."""
    text = answer.text
    assert "Traceback" not in text, (answer.status, text)
    assert ".py" not in text, (answer.status, text)
    # A rooted absolute path under this run's own tree would be a leaked
    # filesystem location; the served route paths (``/metrics/…``) are the
    # caller's own ask and are not filesystem paths, so the one filesystem
    # path this deployment holds — the sealed sidecar — is the thing to keep
    # out, along with the rest of the leak shapes.
    assert "sidecar.enc" not in text, (answer.status, text)


# -- The one route that answers without a token -------------------------------------


def test_healthz_answers_200_with_no_token(deployment) -> None:
    """J8's precondition: the probe answers over the loopback bind with no
    credential — the one route the gate lets through."""
    answer = _request(deployment, "GET", "/healthz", scope=None)
    assert answer.status == 200
    assert answer.body == {"status": "ok"}
    _assert_no_traceback(answer)


def test_healthz_refuses_a_wrong_verb(deployment) -> None:
    """The carve-out is for ``GET /healthz`` alone: a wrong verb is refused
    before the gate, with the ``Allow`` set a caller repairs from."""
    answer = _request(deployment, "POST", "/healthz", scope=None)
    assert answer.status == 405
    assert answer.headers["allow"] == "GET"
    _assert_no_traceback(answer)


# -- Success: each route answers its documented 200/201 over the seeded store -------


def test_the_three_metrics_routes_answer_200_populated(deployment) -> None:
    """J8's observability routes over a store that has something in it: the
    three closed campaigns, the lit canary rail, the seeded regime census —
    each populated, never the empty-store absence the metrics suites pin."""
    fdr = _get(deployment, "/metrics/fdr-deploy", "metrics:read")
    assert fdr.status == 200
    assert len(fdr.body["history"]) == 3
    _assert_no_traceback(fdr)

    status = _get(deployment, "/metrics/instrument-status", "metrics:read")
    assert status.status == 200
    assert status.body["canary"] is True
    _assert_no_traceback(status)

    coverage = _get(deployment, "/metrics/regime-coverage", "metrics:read")
    assert coverage.status == 200
    # ``strata`` is a list of ``[stratum, count]`` rows — the pool's
    # distribution across regimes, one row per named stratum — never a
    # defaulted zero for a stratum nobody counted.
    assert {row[0] for row in coverage.body["strata"]} == {
        "high_vol_trend",
        "low_vol_chop",
        "crash",
    }
    _assert_no_traceback(coverage)


def test_a_fresh_charge_is_appended_and_answered_201(deployment) -> None:
    """J11's ledger route: a node the ledger holds no row for takes the
    insert, and the status says so with 201."""
    document = _charge(str(uuid.uuid4()))
    answer = _post(deployment, "/ledger/debit", document, "evaluator")
    assert answer.status == 201
    assert answer.body["appended"] is True
    _assert_no_traceback(answer)


def test_k_effective_answers_the_derivation_per_epoch(deployment) -> None:
    """J11's read over the seeded ledger: the budget-charging epoch reported
    at 1 and the null node's epoch at 0 — the derivation, never the raw row
    count (the store holds two charges and answers one)."""
    answer = _get(deployment, "/ledger/k-effective", "evaluator")
    assert answer.status == 200
    counts = {epoch: count for epoch, count in answer.body["view"]["counts"]}
    assert counts[deployment.report.epoch_ids[0]] == 1
    assert counts[deployment.report.epoch_ids[1]] == 0
    _assert_no_traceback(answer)


def test_the_observed_curve_answers_200(deployment) -> None:
    """J10's forward route over the seeded node: the two observations the
    demo recorded come back as a sorted curve."""
    answer = _get(
        deployment, f"/forward/decay?node_id={deployment.report.node_id}", "research"
    )
    assert answer.status == 200
    assert len(answer.body["points"]) == 2
    _assert_no_traceback(answer)


def test_a_new_registration_answers_201(deployment) -> None:
    """J9's promotion route: a node the registry holds no row for takes the
    insert, and the status says so with 201."""
    import promotion

    node_id = _insert_node(
        deployment.database_url, campaign_id=deployment.report.campaign_ids[-1]
    )
    answer = _post(
        deployment,
        "/promotion/pre-register",
        {
            "node_id": node_id,
            "epoch_id": deployment.report.epoch_ids[1],
            "criteria": _DEMO_CRITERIA,
        },
        "research",
    )
    assert answer.status == 201
    assert answer.body["created"] is True
    assert answer.body["record"]["criteria_hash"] == promotion.criteria_hash(
        promotion.PromotionCriteria(**_DEMO_CRITERIA)
    )
    _assert_no_traceback(answer)


def test_a_known_node_with_the_bound_engine_answers_200(deployment) -> None:
    """J13's risk route over the bound paper engine: the kill lands first-
    write-wins and the book flattens, 200."""
    answer = _post(deployment, "/risk/halt", {}, "risk")
    assert answer.status == 200
    assert answer.body["instruction"]["instruction"] == "kill"
    _assert_no_traceback(answer)


# -- Retry (idempotent): each route answers its documented 200 for a repeat ---------


def test_a_retried_charge_answers_200_with_the_same_sequence(deployment) -> None:
    """J11's idempotence: the same charge twice is one row — the first POST
    appends (201), the retry answers the standing row (200) with the very
    sequence the first returned."""
    document = _charge(str(uuid.uuid4()))
    first = _post(deployment, "/ledger/debit", document, "evaluator")
    assert first.status == 201
    seq = first.body["record"]["seq"]

    retry = _post(deployment, "/ledger/debit", document, "evaluator")
    assert retry.status == 200
    assert retry.body["appended"] is False
    assert retry.body["record"]["seq"] == seq
    _assert_no_traceback(retry)


def test_an_identical_registration_retry_answers_200(deployment) -> None:
    """J9's idempotence: the same ask twice is one registration — the second
    POST answers the standing row with ``created`` false, not a second row."""
    node_id = _insert_node(
        deployment.database_url, campaign_id=deployment.report.campaign_ids[-1]
    )
    ask = {
        "node_id": node_id,
        "epoch_id": deployment.report.epoch_ids[1],
        "criteria": _DEMO_CRITERIA,
    }
    first = _post(deployment, "/promotion/pre-register", ask, "research")
    assert first.status == 201

    retry = _post(deployment, "/promotion/pre-register", ask, "research")
    assert retry.status == 200
    assert retry.body["created"] is False
    assert retry.body["record"] == first.body["record"]
    _assert_no_traceback(retry)


def test_the_already_promoted_demo_node_answers_200(deployment) -> None:
    """J10's promote route over the seeded node: the demo store already
    opened this node's forward record, so the POST is itself a retry — 200,
    the standing row returned rather than a second one opened."""
    answer = _post(
        deployment,
        "/forward/promote",
        {"node_id": deployment.report.node_id, "forward_days": 90},
        "research",
    )
    assert answer.status == 200
    assert answer.body["created"] is False
    _assert_no_traceback(answer)


def test_a_re_sent_kill_answers_200_changed_false(deployment) -> None:
    """J13's halt is a one-shot write: the first POST sends the kill
    (``changed`` true), a re-send over the already-killed channel writes
    nothing and answers 200 with the standing instruction (``changed``
    false) — the same first-write-wins law the kill channel holds."""
    first = _post(deployment, "/risk/halt", {}, "risk")
    assert first.status == 200
    assert first.body["instruction"]["changed"] is True

    retry = _post(deployment, "/risk/halt", {}, "risk")
    assert retry.status == 200
    assert retry.body["instruction"]["changed"] is False
    _assert_no_traceback(retry)


# -- Absence and refusal: the states a seeded store cannot answer as success --------


def test_an_unknown_node_answers_404(deployment) -> None:
    """The absence the sealed sidecar states: a node it does not know is a
    fact about the world, relayed as 404 with the class that tells an
    unknown node from an unknown path."""
    answer = _post(deployment, "/target", _ask_body(str(uuid.uuid4())), "evaluator")
    assert answer.status == 404
    assert answer.body["error"]["class"] == TARGET_UNKNOWN_NODE_CLASS
    _assert_no_traceback(answer)


def test_a_known_node_with_no_supply_answers_503(deployment) -> None:
    """The refusal: a node the sidecar knows, whose target-series supply this
    deployment has not wired, is the member's own ``TargetPayloadError`` —
    503, a deployment fact, never a fabricated series."""
    for node in (deployment.real_node, deployment.null_node):
        answer = _post(deployment, "/target", _ask_body(node), "evaluator")
        assert answer.status == 503
        assert answer.body["error"]["class"] == "TargetPayloadError"
        _assert_no_traceback(answer)


def test_the_known_refusal_is_byte_identical_for_null_and_real(deployment) -> None:
    """§7.2's information barrier, end to end over the booted server: the
    503 for a known null node and a known real node are byte-identical once
    the node's own identity — the caller's ask, not anything the route
    learned — is masked out."""
    real = _post(deployment, "/target", _ask_body(deployment.real_node), "evaluator")
    null = _post(deployment, "/target", _ask_body(deployment.null_node), "evaluator")
    assert real.status == null.status == 503

    def _masked(answer: _Answer) -> str:
        return answer.text.replace(deployment.real_node, "<node>").replace(
            deployment.null_node, "<node>"
        )

    assert _masked(real) == _masked(null)


def test_a_missing_decay_identity_answers_400(deployment) -> None:
    """The one ask this adapter refuses itself: a GET for a signal that
    states no identity is a 400 about the request, never the store."""
    answer = _get(deployment, "/forward/decay", "research")
    assert answer.status == 400
    assert answer.body["error"]["code"] == "missing_node_id"
    _assert_no_traceback(answer)


def test_a_malformed_ask_answers_400(deployment) -> None:
    """A body that cannot say what it is asking for is the caller's to
    repair — 400, before the sidecar is opened."""
    answer = _post(
        deployment, "/target", _ask_body(str(uuid.uuid4()), horizon=3), "evaluator"
    )
    assert answer.status == 400
    assert answer.body["error"]["code"] == "malformed_body"
    _assert_no_traceback(answer)


# -- Missing token (401) and out-of-scope token (403): the gate before every route --


def test_the_probe_is_the_only_route_that_answers_without_a_token(deployment) -> None:
    """The gate's boundary: every route but ``GET /healthz`` refuses a
    caller with no credential, so an unauthenticated caller cannot
    enumerate the surface by probing it."""
    for route in API_ROUTES:
        answer = _request(deployment, route.verb, route.path, scope=None)
        assert answer.status == 401, f"{route.verb} {route.path} was not 401"
        assert answer.body["error"]["code"] == "missing_token"
        _assert_no_traceback(answer)


def test_every_route_admits_its_own_scope(deployment) -> None:
    """The gate is not a wall: for each of the ten rows, the credential that
    row declares gets *past* the gate — asserted as *not refused by the
    gate*, because a bodyless POST is a malformed ask (400) however good the
    credential, and what this pins is the gate's own decision."""
    for route in API_ROUTES:
        answer = _request(deployment, route.verb, route.path, scope=route.scope)
        assert answer.status not in (401, 403), (
            f"{route.verb} {route.path} refused its own scope {route.scope}"
        )


def test_every_route_refuses_a_token_from_another_scope(deployment) -> None:
    """And the complement: for each row, each of the *other* three scope
    words is a 403 — a real credential of this deployment held to a surface
    it does not reach, so the refusal cannot pass by accident of an unknown
    token."""
    for route in API_ROUTES:
        for scope in API_SCOPES:
            if scope == route.scope:
                continue
            answer = _request(deployment, route.verb, route.path, scope=scope)
            assert answer.status == 403, f"{route.verb} {route.path} accepted {scope}"
            assert answer.body["error"]["code"] == "forbidden_scope"
            _assert_no_traceback(answer)


# -- No response body carries a traceback, across every refusal this store states ---


@pytest.mark.parametrize(
    "method, path, scope, body",
    [
        ("GET", "/healthz", None, None),
        ("GET", "/metrics/fdr-deploy", None, None),
        ("GET", "/metrics/fdr-deploy", "risk", None),
        ("POST", "/risk/halt", "metrics:read", {}),
        ("GET", "/", None, None),
        ("GET", "/nowhere", "metrics:read", None),
        ("POST", "/target", "evaluator", _ask_body(str(uuid.uuid4()))),
        ("POST", "/target", "evaluator", _ask_body(str(uuid.uuid4()), horizon=3)),
        ("GET", "/forward/decay", "research", None),
    ],
)
def test_no_refusal_body_carries_a_traceback_or_a_path(
    deployment, method: str, path: str, scope: str | None, body: Any
) -> None:
    """The envelope's law held over the representative refusals this
    deployment produces — 401, 403, 404, 503, 400 and 405 — each a body an
    operator reads: no stack, no ``.py`` frame, and no filesystem path
    (the sidecar path this deployment actually holds among them)."""
    answer = _request(deployment, method, path, scope=scope, body=body)
    text = answer.text
    assert "Traceback" not in text, (answer.status, text)
    assert ".py" not in text, (answer.status, text)
    assert "sidecar.enc" not in text, (answer.status, text)
