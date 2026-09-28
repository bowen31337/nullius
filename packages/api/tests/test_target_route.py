"""``POST /target`` over HTTP: feature 10's own sentence, clause by clause.

*System serves POST /target as JSON, which returns 404 for a node the
sidecar does not know and an identical 503 refusal for a known null node
and a known real node when no target series supply is wired.*

Three clauses, and each is a separate law rather than three assertions
about one call:

* **404 for a node the sidecar does not know** — §7.2's route reports
  *unknown* as a fact about the world, and the HTTP layer relays that
  fact rather than dressing it as a server refusal.  The body names the
  node that was asked for, so a caller can act on it;
* **an identical 503 for a known null node and a known real node when no
  target series supply is wired** — the feature's hardest clause and the
  reason this file is parametrized over the branch everywhere it can be.
  The refusal is byte-identical, and the test proves it the way the
  constraint states it: by comparing the raw response *bytes* (with the
  node's own identity masked out, since a 503 that named the node it
  could not serve is naming the ask, not the branch), the status, and
  the headers, across two nodes whose only difference is the bit;
* **as JSON** — every one of those bodies goes through the transport's
  one writing door, carries the structured envelope, and the 404 carries
  the class that tells an unknown node from an unknown path.

What this file deliberately does **not** do is test the route's own law.
Feature 112/113/114's contracts — the ask's six terms, the payload's
shape, the same-work discipline — are ``nulloracle``'s suite, and
re-testing them here would be a second, weaker spelling of a contract
that already has an owner.  These tests hold the *transport's* half: that
the composed endpoint is reached with the ask the body stated, that its
answer and its refusal each reach the wire as the status the spec
promises, and that nothing in the transport adds a branch of its own.

The 503 tests wire no series supply, which is the deployment state the
feature names: ``build_target_route`` composes the permutation seam (the
member owns that mechanism) and deliberately leaves ``targets`` unwired
(pipeline step 4's alignment is the evaluator's to supply), so a fresh
composition is *exactly* the deployment the clause is about.  The 200
tests attach a supply the way a deployment would — onto the component the
factory built, never onto a rebuilt endpoint, so the builder's own
permutation stays in place.
"""

from __future__ import annotations

import datetime as dt
import http.client
import json
import threading
import uuid
from typing import Any

import pytest
from nullius_api import ApiServer
from nullius_api.server import TARGET_UNKNOWN_NODE_CLASS

from app.module_loader import Application, create_app

# -- The world under test ---------------------------------------------------------

SYMBOLS = ("BTCUSDT", "ETHUSDT")
DAYS = (dt.date(2026, 1, 5), dt.date(2026, 1, 6))


def _series(request: Any) -> dict[dt.date, dict[str, float]]:
    """The real forward returns pipeline step 4 aligned, as a stand-in.

    Two bars over the cross-section the ask named, with values that
    differ between them — so a test can tell a permuted series from the
    real one by reading values rather than insertion order, which a
    mapping does not carry.
    """
    symbols = getattr(request, "symbols", SYMBOLS)
    return {
        day: {symbol: 0.01 * (index + 1) for index, symbol in enumerate(symbols)}
        for day in DAYS
    }


def _ask_body(node_id: str, **overrides: Any) -> dict[str, Any]:
    """§7.2's six-term body for one node, with any term overridden."""
    body: dict[str, Any] = {
        "node_id": node_id,
        "campaign_id": str(uuid.uuid4()),
        "depth": 2,
        "horizon": 5,
        "symbols": list(SYMBOLS),
        # ISO strings, because §7.2 is a service boundary and ISO is the
        # wire spelling — the member's own record accepts exactly this.
        "date_range": ["2026-01-01", "2026-02-20"],
    }
    body.update(overrides)
    return body


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


def _post(
    server: ApiServer, body: Any, *, raw: bytes | None = None
) -> tuple[int, dict[str, str], bytes]:
    """One ``POST /target``: status, headers and the *raw* body bytes.

    The bytes are returned undecorated rather than parsed, because the
    feature's central clause is about byte-identity: a test that compared
    decoded structures would pass for two bodies that spell one fact two
    ways, which is exactly the difference the information barrier is
    about.
    """
    payload = raw if raw is not None else json.dumps(body).encode("utf-8")
    connection = http.client.HTTPConnection(
        "127.0.0.1", server.server_address[1], timeout=10
    )
    try:
        connection.request(
            "POST", "/target", payload, {"Content-Type": "application/json"}
        )
        response = connection.getresponse()
        return (
            response.status,
            {name.lower(): value for name, value in response.getheaders()},
            response.read(),
        )
    finally:
        connection.close()


def _get(server: ApiServer, path: str) -> tuple[int, dict[str, str], Any]:
    """One no-argument GET, answered as parsed JSON."""
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


def _member_refusal(message: str) -> Exception:
    """A refusal shaped like a served member's own typed error.

    The dispatch recognises a member's refusal by its *module path
    segment*, so the class carries the member's package the way a real
    :class:`~ops.errors.FdrDeployMetricError` does.  Only the
    member-versus-500 routing reads it, never anything about the value.
    """
    cls = type("FdrDeployMetricError", (Exception,), {"__module__": "ops.errors"})
    return cls(message)


class _RefusingEndpoint:
    """A served member's endpoint raising one typed refusal from ``get()``."""

    def __init__(self, refusal: Exception) -> None:
        self._refusal = refusal

    def get(self):
        raise self._refusal


def _with_component(application: Application, name: str, endpoint: Any) -> Application:
    """``application`` with one component replaced, everything else intact.

    The composition is rebuilt rather than mutated: :class:`Application`
    is the factory's own object and the workspace's law is that nothing
    mutates it.  ``order`` is preserved so the composition still describes
    itself the way the factory wrote it.
    """
    components = dict(application.components)
    components[name] = endpoint
    return Application(components=components, order=application.order)


# -- The sealed sidecar the route answers from ------------------------------------


@pytest.fixture
def sidecar_environment(tmp_path, monkeypatch) -> dict[str, str]:
    """Seal §7.1's sidecar for this test and name it in the environment.

    The key is a throwaway ``hex:`` reference and the path is under
    pytest's temporary directory, so no test can seal anything under a
    deployment's key or write a sidecar into a real lake — the same
    isolation the nulloracle member's own suite states, restated here
    because this suite composes the route through the factory rather than
    constructing it.
    """
    monkeypatch.setenv("NULL_SIDECAR_PATH", str(tmp_path / "z0" / "null" / "sidecar.enc"))
    monkeypatch.setenv("NULL_SIDECAR_KEY_REF", "hex:" + "0f" * 32)
    monkeypatch.delenv("NULL_SIDECAR_SERVICE_ACCOUNT", raising=False)
    return {"path": tmp_path}


@pytest.fixture
def sealed_nodes(sidecar_environment, session_application) -> tuple[str, str]:
    """One real node and one null node, sealed into the composed sidecar.

    Both are *known* to the route and they differ only in the bit — which
    is what makes them the pair the feature's second clause is about.  The
    fixture is deliberately named for the bit rather than for a branch:
    the tests below must be able to say which node is which, and the
    route must not.
    """
    sidecar = session_application.get("nulloracle")
    real, null = str(uuid.uuid4()), str(uuid.uuid4())
    sidecar.write(
        [
            _assignment(real, is_null=False),
            _assignment(null, is_null=True),
        ]
    )
    return real, null


def _assignment(node_id: str, *, is_null: bool):
    """One §7.1 assignment, built through the member's own record."""
    import nulloracle

    return nulloracle.NullAssignment(
        node_id=node_id,
        is_null=is_null,
        perm_seed=0 if not is_null else 1,
        block_days=1,
    )


@pytest.fixture
def session_application(sidecar_environment, test_database_url):
    """One composition for the whole test, over the sealed sidecar.

    Composed once and handed to the server, rather than composed per
    server, because the sidecar a node is sealed into must be the same
    one the route reads: two ``create_app()`` calls resolve the same
    environment, but sealing through one and serving through the other
    would make the test's own setup a second world.
    """
    return create_app()


# -- Clause one: 404 for a node the sidecar does not know -------------------------


def test_an_unknown_node_answers_404(
    boot, session_application: Application, sealed_nodes
) -> None:
    """The feature's first clause: a node the sidecar does not know is a
    404 — a fact about the world, relayed rather than re-decided.

    ``sealed_nodes`` is what makes *unknown* a statement about the world
    rather than about the deployment: a sidecar that exists and holds
    other nodes is one that can be *asked* and answer nothing, which is
    the only state in which 404 means what the clause says.  With no
    sidecar written at all the route answers 503 —
    ``test_an_unconfigured_sidecar_answers_503_naming_the_configuration``
    below holds that state — and asserting 404 there would be reading a
    deployment failure as an answer about a node.
    """
    server = boot(session_application)
    status, headers, _ = _post(server, _ask_body(str(uuid.uuid4())))
    assert status == 404
    assert headers["content-type"] == "application/json"


def test_the_unknown_node_answer_names_the_node_that_was_asked_for(
    boot, session_application: Application, sealed_nodes
) -> None:
    """§7.2's route answers a 404 with *everything it knows*, which is
    that the sidecar holds no entry for the node named — so the body
    carries the node, and a caller can act on it."""
    asked = str(uuid.uuid4())
    server = boot(session_application)
    _, _, raw = _post(server, _ask_body(asked))
    body = json.loads(raw)
    assert body["node_id"] == asked
    assert asked in body["error"]["message"]


def test_the_unknown_node_answer_carries_no_payload(
    boot, session_application: Application, sealed_nodes
) -> None:
    """A 404 answers with no series and no directive.  The member's own
    record refuses to carry either on a non-OK status, and the transport
    must not put a ``None`` where the contract says the field does not
    exist — a series here would be the fabricated figure the whole
    member refuses to serve."""
    server = boot(session_application)
    status, _, raw = _post(server, _ask_body(str(uuid.uuid4())))
    # Asserted first, because every refusal on this route carries neither
    # field: without the status the two assertions below would hold for a
    # 503 just as well, and the test would pass for the wrong reason.
    assert status == 404
    body = json.loads(raw)
    assert "target_series" not in body
    assert "charges_budget" not in body


def test_the_unknown_node_is_told_from_an_unknown_path_by_class(
    boot, session_application: Application, sealed_nodes
) -> None:
    """Both refusals are 404s, so the *class* is what a caller routes on —
    an unknown node is an answer about the world, an unknown path is the
    transport saying no route lives there."""
    server = boot(session_application)
    _, _, node_raw = _post(server, _ask_body(str(uuid.uuid4())))
    assert json.loads(node_raw)["error"]["class"] == TARGET_UNKNOWN_NODE_CLASS

    connection = http.client.HTTPConnection(
        "127.0.0.1", server.server_address[1], timeout=10
    )
    try:
        connection.request("GET", "/nowhere")
        response = connection.getresponse()
        path_body = json.loads(response.read())
    finally:
        connection.close()
    assert path_body["error"]["class"] != TARGET_UNKNOWN_NODE_CLASS


def test_an_unknown_node_never_reaches_the_series_supply(
    boot, session_application: Application, sealed_nodes
) -> None:
    """The entry is read first, so an unknown node is answered without the
    supply being consulted at all — and a supply that would raise proves
    it, rather than a call counter that a retry could reset."""
    called: list[Any] = []

    def _never(request: Any) -> dict:
        called.append(request)
        raise AssertionError("the supply was consulted for an unknown node")

    endpoint = session_application.get("nulloracle-target-route")
    endpoint._targets = _never
    try:
        server = boot(session_application)
        status, _, _ = _post(server, _ask_body(str(uuid.uuid4())))
        assert status == 404
        assert called == []
    finally:
        endpoint._targets = None


# -- Clause two: an identical 503 for a known node with no supply wired -----------


@pytest.mark.parametrize("branch", ["real", "null"])
def test_a_known_node_without_a_supply_answers_503(
    boot, session_application: Application, sealed_nodes, branch: str
) -> None:
    """A fresh composition is exactly the deployment the clause names:
    ``build_target_route`` composes the permutation and leaves the series
    supply to pipeline step 4, so a known node is refused rather than
    served half a world."""
    real, null = sealed_nodes
    server = boot(session_application)
    status, headers, _ = _post(server, _ask_body(real if branch == "real" else null))
    assert status == 503
    assert headers["content-type"] == "application/json"


def test_the_no_supply_refusal_is_byte_identical_for_both_branches(
    boot, session_application: Application, sealed_nodes
) -> None:
    """The feature's hardest clause, read the way the constraint states
    it: *the refusal must be byte-identical for null and real nodes*.

    The comparison is over the raw response bytes, the status and the
    headers — not over decoded structures — because decoding would forgive
    a spelling difference, and the whole point is that no reader of this
    response, at any level, can tell which branch produced it.

    The node's own identity is masked out of both bodies before the
    comparison, and that is not a weakening of the claim: the 503 names
    the node it could not serve, which is the *ask* the caller made and
    knows already (it sent it), not anything the route learned.  What the
    mask removes is exactly the difference the caller already holds; what
    it cannot remove is any difference with the bit, because a refusal
    that varied with the branch would vary in the class, the code word or
    the message's shape, and none of those carry a node id.

    The node ids themselves are additionally asserted *different*, so a
    future refactor that accidentally passed one node's id for both
    answers cannot make this test pass by making both bodies equal for
    the wrong reason.
    """
    real, null = sealed_nodes
    assert real != null
    server = boot(session_application)
    real_status, real_headers, real_raw = _post(server, _ask_body(real))
    null_status, null_headers, null_raw = _post(server, _ask_body(null))

    def _masked(raw: bytes) -> bytes:
        return raw.replace(real.encode(), b"<node>").replace(null.encode(), b"<node>")

    assert real_status == null_status == 503
    assert _masked(real_raw) == _masked(null_raw)
    # Headers too: a length or a class of header that varied would leak the
    # branch just as a body would.  ``Date`` is the only header two
    # responses are not promised to share.
    assert {
        name: value for name, value in real_headers.items() if name != "date"
    } == {name: value for name, value in null_headers.items() if name != "date"}


def test_the_refusal_is_identical_for_one_node_sealed_both_ways(
    boot, session_application: Application
) -> None:
    """The clause with the interpretation removed: the *same* node, sealed
    once as a null and once as a real, refused twice.

    The test above compares two different nodes and masks their ids out,
    which is an argument about *why* the unmasked bytes differ.  This one
    makes the argument unnecessary.  One node id, sealed both ways in
    turn, asked the same question each time: there is no caller-side
    difference left to forgive, so the comparison is over the two bodies
    exactly as they came off the wire.

    That is the strongest form the §7.2 barrier can be stated in.  A
    caller who knows the node, the campaign, the depth, the horizon, the
    cross-section and the dates has fixed every input it controls; if the
    two refusals are still equal byte for byte and header for header, then
    the response carries nothing whose value could have come from the
    sidecar.
    """
    import nulloracle

    node = str(uuid.uuid4())
    sidecar = session_application.get("nulloracle")

    def _seal(is_null: bool) -> None:
        sidecar.write(
            [
                nulloracle.NullAssignment(
                    node_id=node,
                    is_null=is_null,
                    perm_seed=1 if is_null else 0,
                    block_days=1,
                )
            ]
        )

    server = boot(session_application)
    _seal(is_null=True)
    null_status, null_headers, null_raw = _post(server, _ask_body(node))
    _seal(is_null=False)
    real_status, real_headers, real_raw = _post(server, _ask_body(node))

    assert null_status == real_status == 503
    # No masking: same node, same ask, so the bytes must simply be equal.
    assert null_raw == real_raw
    assert {
        name: value for name, value in null_headers.items() if name != "date"
    } == {name: value for name, value in real_headers.items() if name != "date"}
    # And the body is the *refusal* rather than some coincidence of two
    # empty answers — the seal really did change the branch in between.
    assert json.loads(null_raw)["error"]["class"] == "TargetPayloadError"


def test_the_no_supply_refusal_names_the_missing_supply_and_not_the_branch(
    boot, session_application: Application, sealed_nodes
) -> None:
    """The refusal is the member's own ``TargetPayloadError`` — a word
    §7.2 allows across the barrier because it names a *deployment* fact.
    What must never appear is the branch: neither the word for the bit nor
    the word for the world it plants."""
    real, null = sealed_nodes
    server = boot(session_application)
    for node in (real, null):
        _, _, raw = _post(server, _ask_body(node))
        body = json.loads(raw)
        assert body["error"]["class"] == "TargetPayloadError"
        assert body["error"]["code"] == "member_refusal"
        text = json.dumps(body)
        for forbidden in ("is_null", "permute", "permut", "block_permute"):
            assert forbidden not in text, f"the refusal names {forbidden!r}"
    # And the two branches are refused by one mechanism: an identical
    # class, which is what a caller routes on rather than the message.
    real_body = json.loads(_post(server, _ask_body(real))[2])
    null_body = json.loads(_post(server, _ask_body(null))[2])
    assert real_body["error"]["class"] == null_body["error"]["class"]
    assert real_body["error"]["code"] == null_body["error"]["code"]


def test_the_refusal_is_the_same_class_not_a_transport_invention(
    boot, session_application: Application, sealed_nodes
) -> None:
    """The transport relays the member's refusal rather than inventing
    one: the class is the very class the member's own traceback names, and
    the transport's own class constants are none of them."""
    from nullius_api.server import (
        COMPONENT_UNCONFIGURED_CLASS,
        MALFORMED_REQUEST_CLASS,
        ROUTE_NOT_IMPLEMENTED_CLASS,
    )

    real, null = sealed_nodes
    server = boot(session_application)
    for node in (real, null):
        _, _, raw = _post(server, _ask_body(node))
        answered = json.loads(raw)["error"]["class"]
        assert answered == "TargetPayloadError"
        assert answered not in {
            COMPONENT_UNCONFIGURED_CLASS,
            MALFORMED_REQUEST_CLASS,
            ROUTE_NOT_IMPLEMENTED_CLASS,
        }


def test_no_supply_refusal_leaks_no_traceback_or_path(
    boot, session_application: Application, sealed_nodes, tmp_path
) -> None:
    """The envelope law holds over this route's refusal too — and the
    sidecar path is the one this deployment actually holds, so a leaked
    path would name something real."""
    real, null = sealed_nodes
    server = boot(session_application)
    for node in (real, null):
        _, _, raw = _post(server, _ask_body(node))
        text = raw.decode()
        assert "Traceback" not in text
        assert str(tmp_path) not in text
        assert ".py" not in text


# -- The success path: the member's own answer, passed straight through -----------


@pytest.mark.parametrize("branch", ["real", "null"])
def test_a_known_node_with_a_supply_wired_answers_200(
    boot, session_application: Application, sealed_nodes, branch: str
) -> None:
    """With pipeline step 4's alignment attached the way a deployment
    attaches it, the route serves §7.2's payload: the series and the
    opaque directive."""
    real, null = sealed_nodes
    endpoint = session_application.get("nulloracle-target-route")
    endpoint._targets = _series
    try:
        server = boot(session_application)
        status, headers, raw = _post(server, _ask_body(real if branch == "real" else null))
        assert status == 200
        assert headers["content-type"] == "application/json"
        body = json.loads(raw)
        assert body["target_series"] == {
            "2026-01-05": {"BTCUSDT": 0.01, "ETHUSDT": 0.02},
            "2026-01-06": {"BTCUSDT": 0.01, "ETHUSDT": 0.02},
        }
        assert isinstance(body["charges_budget"], bool)
    finally:
        endpoint._targets = None


def test_the_directive_is_the_members_own_bit_and_the_transport_adds_none(
    boot, session_application: Application, sealed_nodes
) -> None:
    """``charges_budget`` is ``True`` for the real node and ``False`` for
    the null one — the member's own rule (§8: a null node's signal was
    never compared to real forward returns, so it spends no statistical
    budget), relayed unchanged.  The transport computes nothing here; it
    could not fabricate this figure if it wanted to, because it never
    inspects the payload at all."""
    real, null = sealed_nodes
    endpoint = session_application.get("nulloracle-target-route")
    endpoint._targets = _series
    try:
        server = boot(session_application)
        real_body = json.loads(_post(server, _ask_body(real))[2])
        null_body = json.loads(_post(server, _ask_body(null))[2])
        assert real_body["charges_budget"] is True
        assert null_body["charges_budget"] is False
    finally:
        endpoint._targets = None


def test_the_two_successes_have_the_same_shape(
    boot, session_application: Application, sealed_nodes
) -> None:
    """Feature 114's shape half, over HTTP: the two 200s differ in their
    values and in one sanctioned bit and in nothing else — same keys, same
    grid, same symbol names.  A body whose *shape* varied would be the
    branch oracle §7.2 forbids, one level up from the member that took
    care not to send it."""
    real, null = sealed_nodes
    endpoint = session_application.get("nulloracle-target-route")
    endpoint._targets = _series
    try:
        server = boot(session_application)
        real_body = json.loads(_post(server, _ask_body(real))[2])
        null_body = json.loads(_post(server, _ask_body(null))[2])
    finally:
        endpoint._targets = None

    assert set(real_body) == set(null_body)
    assert set(real_body["target_series"]) == set(null_body["target_series"])
    for day in real_body["target_series"]:
        assert set(real_body["target_series"][day]) == set(
            null_body["target_series"][day]
        )
    # Erasing the values leaves nothing but the one sanctioned crossing.
    def _keys_only(body):
        return {
            "status": body["status"],
            "grid": sorted(body["target_series"]),
            "symbols": sorted(
                {s for row in body["target_series"].values() for s in row}
            ),
        }

    assert _keys_only(real_body) == _keys_only(null_body)


# -- The body: read, relayed to the member, refused by the member -----------------


def test_the_body_terms_reach_the_members_own_request_record(
    boot, session_application: Application, sealed_nodes
) -> None:
    """The transport builds no request of its own: the body's six terms go
    through ``TargetRequest``'s constructor, so §7.2's contract is
    validated by the module that owns it and a term is never re-spelled
    here.  A malformed body is answered with that module's own refusal."""
    real, _ = sealed_nodes
    server = boot(session_application)
    # A horizon outside the five the spec aligns — refused by the member's
    # own record, whose message names the closed set.
    status, _, raw = _post(server, _ask_body(real, horizon=3))
    assert status == 400
    body = json.loads(raw)
    assert body["error"]["code"] == "malformed_body"
    assert "1, 2, 5, 10, 20" in body["error"]["message"]


@pytest.mark.parametrize(
    "overrides",
    [
        {"node_id": "not-a-uuid"},
        {"depth": -1},
        {"depth": True},
        {"horizon": 3},
        {"symbols": []},
        {"symbols": "BTCUSDT"},
        {"date_range": ["2026-02-20", "2026-01-01"]},
        {"date_range": ["2026-01-01"]},
    ],
)
def test_a_malformed_ask_answers_400(
    boot, session_application: Application, overrides: dict
) -> None:
    """Feature 5's malformed-body status, over the one route that reads a
    body in this build.  Every term §7.2 names is checked, because the
    point is that the *body's* contract is the caller's to repair — a 503
    here would tell them to escalate a deployment that is working."""
    body = _ask_body(str(uuid.uuid4()))
    body.update(overrides)
    server = boot(session_application)
    status, _, raw = _post(server, body)
    assert status == 400
    assert json.loads(raw)["error"]["code"] == "malformed_body"


def test_a_malformed_ask_is_refused_before_the_sidecar_is_opened(
    boot, session_application: Application
) -> None:
    """A malformed body is refused without the sidecar being read — so
    whether the ask was malformed is a fact about the body and never about
    the node it named, and this door cannot become a second channel the
    branch leaks through.  Asserted over the *pair*: a node that is sealed
    and a node that is not are refused identically for the same malformed
    term."""
    import nulloracle

    sidecar = session_application.get("nulloracle")
    known = str(uuid.uuid4())
    sidecar.write([nulloracle.NullAssignment(node_id=known, is_null=True, perm_seed=1)])
    unknown = str(uuid.uuid4())

    server = boot(session_application)
    known_status, _, known_raw = _post(server, _ask_body(known, horizon=3))
    unknown_status, _, unknown_raw = _post(server, _ask_body(unknown, horizon=3))
    assert known_status == unknown_status == 400
    assert (
        known_raw.replace(known.encode(), b"<node>")
        == unknown_raw.replace(unknown.encode(), b"<node>")
    )


@pytest.mark.parametrize(
    "raw",
    [
        b"{nope",
        b"[1, 2, 3]",
        b'"a string"',
        b"",
        b"   ",
    ],
)
def test_a_body_the_reader_cannot_use_is_refused_by_name(
    boot, session_application: Application, raw: bytes
) -> None:
    """A body that is not a JSON object is refused by the transport's own
    reader — feature 5's 400 — and the refusal never echoes the body: an
    exception message that quoted request-derived text is exactly what the
    no-token-no-body-in-a-log law forbids."""
    server = boot(session_application)
    status, _, answer = _post(server, None, raw=raw)
    assert status == 400
    body = json.loads(answer)
    assert body["error"]["code"] == "malformed_body"
    assert "nope" not in answer.decode()
    assert "a string" not in answer.decode()


def test_a_request_with_no_body_at_all_is_a_malformed_ask(
    boot, session_application: Application
) -> None:
    """No body is *no ask stated*, and §7.2's six terms are all required —
    so the member refuses it, and the transport answers the same 400 it
    answers any other body that cannot say what it is asking for."""
    server = boot(session_application)
    status, _, raw = _post(server, None, raw=b"")
    assert status == 400
    assert json.loads(raw)["error"]["code"] == "malformed_body"


# -- The composition this route needs, and what an absent one answers --------------


def test_an_unconfigured_sidecar_answers_503_naming_the_configuration(
    boot, monkeypatch
) -> None:
    """J12's third expected result: with no sidecar configured the route
    is *unconfigured*, which is a different fact from a refusal a known
    node produced — and the body names the configuration that would fix
    it rather than the node."""
    for name in ("NULL_SIDECAR_PATH", "NULL_SIDECAR_KEY_REF"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.delenv("LAKE_ROOT", raising=False)
    server = boot(create_app())
    status, _, raw = _post(server, _ask_body(str(uuid.uuid4())))
    assert status == 503
    body = json.loads(raw)
    assert body["error"]["code"] == "component_unconfigured"
    assert "nulloracle-target-route" in body["error"]["message"]
    assert "NULL_SIDECAR_PATH" in body["error"]["message"]


def test_a_configured_but_unopenable_sidecar_never_names_its_path(
    boot, monkeypatch, tmp_path
) -> None:
    """The envelope's last law, over the one deployment state that reaches
    it: a sidecar that is *configured* — so the component resolves and the
    route is served — but whose file is not there.

    The member's own refusal names where it looked, and it should: an
    operator reading a log needs the path.  A *body* must not carry it, so
    the transport redacts it on the way out and publishes the rest of the
    sentence unchanged — the caller still reads the code word and the one
    repair, the class is still the member's own, and the deployment's
    directory layout stays out of a response.

    This is the state a real deployment hits by pointing
    ``NULL_SIDECAR_PATH`` at a lake the service account cannot reach, and
    it is reachable only through this route: ``/target`` is the one served
    route that opens the sidecar.
    """
    monkeypatch.setenv(
        "NULL_SIDECAR_PATH", str(tmp_path / "z0" / "null" / "sidecar.enc")
    )
    monkeypatch.setenv("NULL_SIDECAR_KEY_REF", "hex:" + "0f" * 32)
    server = boot(create_app())
    status, _, raw = _post(server, _ask_body(str(uuid.uuid4())))
    assert status == 503
    text = raw.decode()
    body = json.loads(raw)
    # The refusal is still the member's, and still says what went missing.
    assert body["error"]["class"] == "SidecarStoreError"
    assert body["error"]["code"] == "member_refusal"
    assert "no sidecar exists at" in body["error"]["message"]
    # And the path it named is gone, along with the rest of the leak shapes.
    assert str(tmp_path) not in text
    assert "sidecar.enc" not in text
    assert "/" not in body["error"]["message"]
    assert "Traceback" not in text
    assert ".py" not in text


@pytest.mark.parametrize(
    "message",
    [
        (
            "node 4f2b has a series to serve and this endpoint holds no seam "
            "to serve it from; §7.2's response carries the real forward "
            "returns pipeline step 4 aligned"
        ),
        (
            "no fdr_deploy_metric row for campaign c-1; the repair is a "
            "computed_at instant the store holds"
        ),
        "fdr_deploy_metric: the store refused the trend read",
    ],
)
def test_a_message_with_no_filesystem_path_is_published_word_for_word(
    message: str,
) -> None:
    """The redaction is by shape, not by member: a refusal that names a
    node, a supply, a campaign or a figure has no filesystem path in it,
    so it must reach the caller unchanged.  This is the guard against a
    redaction that quietly rewrites the messages that were never the
    problem — the ones the whole verbatim-members'-message law exists to
    publish."""
    from nullius_api.server import _publish

    assert _publish(message) == message


@pytest.mark.parametrize(
    "message",
    [
        # The members' own refusals very often name the route they were
        # answering; that path is the caller's own ask coming back.
        "could not answer GET /metrics/fdr-deploy: the store refused",
        "GET /forward/decay must state the signal it is asking about",
        "POST /target: the oracle holds no seam",
    ],
)
def test_a_route_path_in_a_message_is_not_a_filesystem_path(
    message: str,
) -> None:
    """A rooted run of text is not by itself a filesystem path, and no
    pattern can tell ``/metrics/fdr-deploy`` from ``/srv/null`` by shape.
    The separator is the transport's own route table: a path it actually
    serves is the caller's ask, published verbatim; anything else is the
    deployment's filesystem, redacted."""
    from nullius_api.routes import API_ROUTES
    from nullius_api.server import _publish

    served = {route.path for route in API_ROUTES}
    assert _publish(message, served_paths=served) == message
    # And the same text minus the exemption is redacted — which is what
    # makes the exemption load-bearing rather than vacuous.
    assert _publish(message) != message


def test_a_members_route_path_survives_the_redaction_over_the_wire(
    boot, session_application: Application, sealed_nodes
) -> None:
    """The other half of the redaction's contract, through the dispatch.

    ``ops``' own refusal composes *"could not answer GET
    /metrics/fdr-deploy: …"* — a real member message with a route path in
    it.  The redaction must let that through untouched: it is the
    caller's own ask coming back, and rewriting it would break the
    verbatim-message law for every refusal that names its route.

    Driven end to end rather than by calling :func:`_publish`, so the
    route table the door passes in is the *real* composition's — which is
    the part a unit test of the function cannot check.  The refusal is
    raised by a stub endpoint standing in for the member's own typed
    error; only the dispatch's member/500 routing reads its class.
    """
    refusal = _member_refusal(
        "could not answer GET /metrics/fdr-deploy: the FDR_deploy store "
        "refused the trend read; the repair is a database the service "
        "account can read"
    )
    application = _with_component(
        session_application, "ops-fdr-deploy", _RefusingEndpoint(refusal)
    )
    server = boot(application)
    status, _, body = _get(server, "/metrics/fdr-deploy")
    assert status == 503
    assert body["error"]["class"] == "FdrDeployMetricError"
    assert "/metrics/fdr-deploy" in body["error"]["message"]
    assert "<path>" not in body["error"]["message"]


def test_the_route_is_served_through_the_composed_component(
    session_application: Application
) -> None:
    """The transport holds no route logic of its own: what it serves at
    ``POST /target`` is the very component the factory built — the
    endpoint identity is asserted, not merely its behaviour."""
    from nullius_api.routes import resolve_routes

    resolved = {
        row.route.path: row.endpoint for row in resolve_routes(session_application)
    }
    assert resolved["/target"] is session_application.get("nulloracle-target-route")
