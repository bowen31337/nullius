"""``POST /promotion/pre-register`` over HTTP.

The route feature 291 exposes in-process and feature 8 of
additions_spec_journeys.xml serves over the wire, held to this build's own
sentence: *System serves POST /promotion/pre-register as JSON, which
returns 201 for a new registration, 200 for an identical retry, 409 when
the node is re-registered with different criteria and 422 when the node or
epoch row is absent.*

Four clauses, each its own section below:

* **201 for a new registration** — a node the registry holds no row for
  takes the insert, and the status says so.  The body carries the member's
  own record: the ``criteria_hash`` feature 291's sentence promises, and
  the ``pre_registered_at`` its §13 item 7 ordering is stated in.
* **200 for an identical retry** — the same ask arriving twice is one
  registration, and the second POST answers the standing row with
  ``created`` false.  The status is derived from *that flag* and nothing
  else, so a retry can never be answered as a creation, and the standing
  ``pre_registered_at`` comes back unmoved rather than re-stamped.
* **409 for a re-registration with different criteria** — the member's own
  :class:`~promotion.errors.PromotionConflictError`, answered with the
  member's message verbatim (both hashes named) and *not* folded into the
  generic member-refusal 503 that a store fault wears.
* **422 when the node or epoch row is absent** — the member's own
  :class:`~promotion.errors.PromotionParentAbsentError`, whose repair is to
  the registration rather than to the deployment; the two absent parents
  (a node the tree does not hold, an epoch nobody sealed) answer the same
  status with the absent table named.

The 400 door is pinned beside them, because the split is the point: a body
that cannot say what it is asking for is the caller's to repair, and it must
never be confused with either of the two typed refusals above — every one of
those three travels through a different door.

The suite composes the real application (``create_app()``) over a per-test
sqlite store and seeds through the members' own public seams — the demo
seed's ``node`` and ``epoch_ledger`` parent rows plus
:meth:`promotion.pre_register.PreRegistrations.pre_register` for the
standing-registration states — never through a second spelling of a row a
member already owns.
"""

from __future__ import annotations

import datetime as dt
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
from nullius_api import (
    PROMOTION_CONFLICT_CODE,
    PROMOTION_PARENT_ABSENT_CODE,
    ApiServer,
)
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


# -- Seeding the states the route's refusals need -----------------------------------

#: The six-term criteria document, spelled exactly as
#: :meth:`promotion.criteria.PromotionCriteria.document` renders it — the
#: inverse :func:`promotion.pre_register._criteria_from_document` rebuilds,
#: so a body this suite posts hashes to the same digest a criteria value
#: would.
_CRITERIA = {
    "theta": 0.3,
    "alpha": 0.05,
    "max_fdr_deploy": 0.25,
    "min_worlds": 50,
    "min_coverage_strata": 3,
    "min_forward_days": 90,
}

#: A second document differing in exactly one term — the smallest honest
#: *different criteria*, so the 409 test differs from the 200 test by the
#: one thing it is about.
_OTHER_CRITERIA = {**_CRITERIA, "theta": 0.4}


def _sqlite_path(database_url: str) -> str:
    """Translate ``sqlite:///…`` the same way every store in this workspace
    does — restated here rather than imported, because a caller outside the
    member never reaches into its private helpers."""
    return unquote(urlparse(database_url).path).removeprefix("/")


def _insert_node(url: str, *, campaign_id: str) -> str:
    """A ``node`` row the registry can reference — the same shape
    :mod:`nullius_api.demo` inserts, for a node this suite registers on its
    own rather than through the demo seed's single fixed identity."""
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
                    hashlib.sha256(b"test-evaluator").hexdigest(),
                    hashlib.sha256(b"test-snapshot").hexdigest(),
                    hashlib.sha256(b"test-cost-model").hexdigest(),
                ),
            )
    finally:
        connection.close()
    return node_id


def _seal_epoch(url: str, epoch_id: str) -> None:
    """An ``epoch_ledger`` row — a holdout the sealing process would have
    written, inserted directly for the reason the demo seed's own parent
    rows are: it is not this member's job and no store owns it."""
    connection = sqlite3.connect(_sqlite_path(url))
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        with connection:
            connection.execute(
                "INSERT OR IGNORE INTO epoch_ledger "
                "(epoch_id, sealed_at, promotion_decisions_served, retired) "
                "VALUES (?, ?, ?, ?)",
                (epoch_id, "2026-01-01T00:00:00+00:00", 0, 0),
            )
    finally:
        connection.close()


def _standing_registration(url: str, node_id: str, epoch_id: str, criteria: dict) -> None:
    """Record a node's criteria through the member's own store, so a later
    POST is genuinely a re-registration against a standing row."""
    import promotion

    promotion.PreRegistrations(url).pre_register(
        node_id,
        epoch_id,
        promotion.PromotionCriteria(**criteria),
        pre_registered_at=dt.datetime(2026, 4, 1, tzinfo=dt.UTC),
    )


@pytest.fixture
def seeded(test_database_url: str):
    """The demo store: three campaigns, three sealed epochs and the
    pre-registered, decided node — the parent rows a registration needs."""
    report = seed_demo_store(test_database_url)
    return report, test_database_url


# -- 201 for a new registration ------------------------------------------------------


def test_a_new_registration_answers_201(seeded, boot) -> None:
    """A node the registry holds no row for takes the insert: 201, the
    member's own record, and the criteria hash feature 291 promises."""
    report, url = seeded
    node_id = _insert_node(url, campaign_id=report.campaign_ids[-1])
    server = boot(create_app())
    status, headers, body = _post(
        server,
        "/promotion/pre-register",
        {"node_id": node_id, "epoch_id": report.epoch_ids[1], "criteria": _CRITERIA},
    )
    assert status == 201
    assert headers["content-type"] == "application/json"
    assert body["created"] is True
    assert body["record"]["node_id"] == node_id
    assert body["record"]["epoch_id"] == report.epoch_ids[1]
    # The hash is 64 lowercase hex characters — the spelling 0108's
    # ``CHAR(64)`` declares — and the row is born open (``decided_at``
    # NULL), which is §13 item 7's ordering stated as a fact about the row.
    assert len(body["record"]["criteria_hash"]) == 64
    assert set(body["record"]["criteria_hash"]) <= set("0123456789abcdef")
    assert body["record"]["decided_at"] is None
    assert body["record"]["pre_registered_at"]


def test_the_registration_is_readable_back_from_the_table(seeded, boot) -> None:
    """The row the 201 wrote is the row the table holds — the transport
    reports the registry's state, it does not compose a body of its own."""
    report, url = seeded
    node_id = _insert_node(url, campaign_id=report.campaign_ids[-1])
    server = boot(create_app())
    _, _, body = _post(
        server,
        "/promotion/pre-register",
        {"node_id": node_id, "epoch_id": report.epoch_ids[1], "criteria": _CRITERIA},
    )
    connection = sqlite3.connect(_sqlite_path(url))
    try:
        row = connection.execute(
            "SELECT node_id, epoch_id, criteria_hash, decided_at "
            "FROM promotion_registry WHERE node_id = ?",
            (node_id,),
        ).fetchone()
    finally:
        connection.close()
    assert row is not None
    assert row[0] == node_id
    assert row[1] == report.epoch_ids[1]
    assert row[2] == body["record"]["criteria_hash"]
    assert row[3] is None


def test_the_hash_on_the_wire_is_the_criteria_digest(seeded, boot) -> None:
    """The 201 body's hash is the sha256 of the canonical six-term
    document — recomputed here from the member's own value, never
    re-derived by the transport."""
    import promotion

    report, url = seeded
    node_id = _insert_node(url, campaign_id=report.campaign_ids[-1])
    server = boot(create_app())
    _, _, body = _post(
        server,
        "/promotion/pre-register",
        {"node_id": node_id, "epoch_id": report.epoch_ids[1], "criteria": _CRITERIA},
    )
    assert body["record"]["criteria_hash"] == promotion.criteria_hash(
        promotion.PromotionCriteria(**_CRITERIA)
    )


# -- 200 for an identical retry ------------------------------------------------------


def test_an_identical_retry_answers_200_with_the_standing_row(seeded, boot) -> None:
    """The same ask twice is one registration: the second POST answers 200
    with ``created`` false and the row the first one wrote."""
    report, url = seeded
    node_id = _insert_node(url, campaign_id=report.campaign_ids[-1])
    server = boot(create_app())
    ask = {"node_id": node_id, "epoch_id": report.epoch_ids[1], "criteria": _CRITERIA}

    first_status, _, first = _post(server, "/promotion/pre-register", ask)
    second_status, _, second = _post(server, "/promotion/pre-register", ask)

    assert first_status == 201
    assert second_status == 200
    assert second["created"] is False
    assert second["record"] == first["record"]


def test_a_retry_does_not_move_the_standing_pre_registered_at(seeded, boot) -> None:
    """The instant the criteria were fixed is the instant they were *first*
    fixed: a retry answers the standing stamp rather than re-stamping, so
    the response never claims a freshness the retry does not have."""
    report, url = seeded
    node_id = _insert_node(url, campaign_id=report.campaign_ids[-1])
    _standing_registration(url, node_id, report.epoch_ids[1], _CRITERIA)
    server = boot(create_app())
    status, _, body = _post(
        server,
        "/promotion/pre-register",
        {"node_id": node_id, "epoch_id": report.epoch_ids[1], "criteria": _CRITERIA},
    )
    assert status == 200
    assert body["record"]["pre_registered_at"].startswith("2026-04-01")


def test_only_one_row_exists_after_a_retry(seeded, boot) -> None:
    """The retry wrote nothing — the one-row-per-node law §13 item 7
    implies, read off the table rather than off the body."""
    report, url = seeded
    node_id = _insert_node(url, campaign_id=report.campaign_ids[-1])
    server = boot(create_app())
    ask = {"node_id": node_id, "epoch_id": report.epoch_ids[1], "criteria": _CRITERIA}
    _post(server, "/promotion/pre-register", ask)
    _post(server, "/promotion/pre-register", ask)
    connection = sqlite3.connect(_sqlite_path(url))
    try:
        count = connection.execute(
            "SELECT COUNT(*) FROM promotion_registry WHERE node_id = ?", (node_id,)
        ).fetchone()[0]
    finally:
        connection.close()
    assert count == 1


# -- 409 for a re-registration with different criteria -------------------------------


def test_a_different_criteria_re_registration_answers_409(seeded, boot) -> None:
    """The node already holds criteria, and this ask states others — the
    member's own conflict class, answered 409 with the member's word."""
    report, url = seeded
    node_id = _insert_node(url, campaign_id=report.campaign_ids[-1])
    _standing_registration(url, node_id, report.epoch_ids[1], _CRITERIA)
    server = boot(create_app())
    status, _, body = _post(
        server,
        "/promotion/pre-register",
        {
            "node_id": node_id,
            "epoch_id": report.epoch_ids[1],
            "criteria": _OTHER_CRITERIA,
        },
    )
    assert status == 409
    assert body["error"]["code"] == "promotion_criteria_conflict"
    assert body["error"]["class"] == "PromotionConflictError"


def test_the_409_names_both_criteria_hashes(seeded, boot) -> None:
    """The conflict is decidable from the body alone: the hash the row
    stands at and the hash this ask states, both in the message."""
    import promotion

    report, url = seeded
    node_id = _insert_node(url, campaign_id=report.campaign_ids[-1])
    _standing_registration(url, node_id, report.epoch_ids[1], _CRITERIA)
    server = boot(create_app())
    _, _, body = _post(
        server,
        "/promotion/pre-register",
        {
            "node_id": node_id,
            "epoch_id": report.epoch_ids[1],
            "criteria": _OTHER_CRITERIA,
        },
    )
    message = body["error"]["message"]
    assert promotion.criteria_hash(promotion.PromotionCriteria(**_CRITERIA)) in message
    assert (
        promotion.criteria_hash(promotion.PromotionCriteria(**_OTHER_CRITERIA))
        in message
    )


def test_the_standing_row_is_untouched_by_the_refused_409(seeded, boot) -> None:
    """The refusal is a refusal to *write*: the row the node held is still
    the row it holds, hash and stamp alike."""
    import promotion

    report, url = seeded
    node_id = _insert_node(url, campaign_id=report.campaign_ids[-1])
    _standing_registration(url, node_id, report.epoch_ids[1], _CRITERIA)
    server = boot(create_app())
    _post(
        server,
        "/promotion/pre-register",
        {
            "node_id": node_id,
            "epoch_id": report.epoch_ids[1],
            "criteria": _OTHER_CRITERIA,
        },
    )
    connection = sqlite3.connect(_sqlite_path(url))
    try:
        row = connection.execute(
            "SELECT criteria_hash, pre_registered_at FROM promotion_registry "
            "WHERE node_id = ?",
            (node_id,),
        ).fetchone()
    finally:
        connection.close()
    assert row[0] == promotion.criteria_hash(promotion.PromotionCriteria(**_CRITERIA))
    assert row[1].startswith("2026-04-01")


def test_a_conflict_is_never_reported_as_a_malformed_body(seeded, boot) -> None:
    """The two 4xx doors are different doors: a well-formed ask that
    conflicts with a row is a 409, never the 400 a body that cannot say
    what it is asking for wears."""
    report, url = seeded
    node_id = _insert_node(url, campaign_id=report.campaign_ids[-1])
    _standing_registration(url, node_id, report.epoch_ids[1], _CRITERIA)
    server = boot(create_app())
    status, _, body = _post(
        server,
        "/promotion/pre-register",
        {
            "node_id": node_id,
            "epoch_id": report.epoch_ids[1],
            "criteria": _OTHER_CRITERIA,
        },
    )
    assert status != 400
    assert body["error"]["class"] != "MalformedRequestError"


def test_a_conflict_is_never_reported_as_a_store_failure(seeded, boot) -> None:
    """A conflict is a fact about a row, not a broken deployment — it must
    not fall into the generic member-refusal 503 a store fault wears."""
    report, url = seeded
    node_id = _insert_node(url, campaign_id=report.campaign_ids[-1])
    _standing_registration(url, node_id, report.epoch_ids[1], _CRITERIA)
    server = boot(create_app())
    status, _, body = _post(
        server,
        "/promotion/pre-register",
        {
            "node_id": node_id,
            "epoch_id": report.epoch_ids[1],
            "criteria": _OTHER_CRITERIA,
        },
    )
    assert status != 503
    assert body["error"]["code"] != "member_refusal"


# -- 422 when the node or epoch row is absent ----------------------------------------


def test_an_absent_node_answers_422(seeded, boot) -> None:
    """A node the ``node`` table does not hold: the ask is well formed and
    the row it references does not exist — 422, naming the absent parent."""
    report, _ = seeded
    server = boot(create_app())
    status, _, body = _post(
        server,
        "/promotion/pre-register",
        {
            "node_id": str(uuid.uuid4()),
            "epoch_id": report.epoch_ids[1],
            "criteria": _CRITERIA,
        },
    )
    assert status == 422
    assert body["error"]["code"] == "promotion_parent_absent"
    assert body["error"]["class"] == "PromotionParentAbsentError"
    assert "node" in body["error"]["message"]


def test_an_absent_epoch_answers_422(seeded, boot) -> None:
    """An epoch nobody sealed: the same status and the same class, with the
    *other* absent table named — the repair differs by parent, so the body
    must say which."""
    report, url = seeded
    node_id = _insert_node(url, campaign_id=report.campaign_ids[-1])
    server = boot(create_app())
    status, _, body = _post(
        server,
        "/promotion/pre-register",
        {"node_id": node_id, "epoch_id": "no-such-epoch", "criteria": _CRITERIA},
    )
    assert status == 422
    assert body["error"]["code"] == "promotion_parent_absent"
    assert body["error"]["class"] == "PromotionParentAbsentError"
    assert "epoch_ledger" in body["error"]["message"]
    assert "no-such-epoch" in body["error"]["message"]


def test_an_absent_parent_is_never_reported_as_a_store_failure(seeded, boot) -> None:
    """The missing parent is not an unwritable store: nothing was attempted
    and the database is reachable, so 422 rather than the door's 503."""
    report, _ = seeded
    server = boot(create_app())
    status, _, body = _post(
        server,
        "/promotion/pre-register",
        {
            "node_id": str(uuid.uuid4()),
            "epoch_id": report.epoch_ids[1],
            "criteria": _CRITERIA,
        },
    )
    assert status != 503
    assert body["error"]["code"] != "member_refusal"


def test_an_absent_parent_writes_no_row(seeded, boot) -> None:
    """The refusal happens before the insert: the registry holds nothing
    for the node, and no row was left behind by the attempt."""
    report, url = seeded
    node_id = str(uuid.uuid4())
    server = boot(create_app())
    _post(
        server,
        "/promotion/pre-register",
        {"node_id": node_id, "epoch_id": report.epoch_ids[1], "criteria": _CRITERIA},
    )
    connection = sqlite3.connect(_sqlite_path(url))
    try:
        count = connection.execute(
            "SELECT COUNT(*) FROM promotion_registry WHERE node_id = ?", (node_id,)
        ).fetchone()[0]
    finally:
        connection.close()
    assert count == 0


def test_the_demo_nodes_epoch_is_already_a_registration(seeded, boot) -> None:
    """The demo seed pre-registered its own node against its serving epoch,
    so re-posting *its* criteria is the retry branch — the fixture is a
    standing row, not a free identity."""
    report, _ = seeded
    server = boot(create_app())
    status, _, body = _post(
        server,
        "/promotion/pre-register",
        {
            "node_id": report.node_id,
            "epoch_id": report.epoch_ids[0],
            "criteria": _CRITERIA,
        },
    )
    assert status == 200
    assert body["created"] is False
    assert body["record"]["node_id"] == report.node_id


# -- 400 for a body that cannot say what it is asking for ----------------------------


@pytest.mark.parametrize(
    "overrides",
    [
        {"node_id": "not-a-uuid"},
        {"node_id": None},
        {"epoch_id": None},
        {"epoch_id": ""},
        {"epoch_id": "   "},
        {"criteria": None},
        {"criteria": "not-a-document"},
        {"criteria": {}},
        {"criteria": {**_CRITERIA, "min_world": 50}},  # the near-miss typo
        {"criteria": {k: v for k, v in _CRITERIA.items() if k != "theta"}},
    ],
)
def test_a_malformed_body_answers_400(seeded, boot, overrides: dict) -> None:
    """Every term the request contract states is validated by the member's
    own constructor — a body that fails is the caller's to repair, 400."""
    report, _ = seeded
    body = {
        "node_id": report.node_id,
        "epoch_id": report.epoch_ids[1],
        "criteria": _CRITERIA,
    }
    body.update(overrides)
    server = boot(create_app())
    status, _, answer = _post(server, "/promotion/pre-register", body)
    assert status == 400
    assert answer["error"]["code"] == "malformed_body"
    assert answer["error"]["class"] == "MalformedRequestError"


def test_a_missing_body_answers_400(seeded, boot) -> None:
    server = boot(create_app())
    status, _, answer = _post(server, "/promotion/pre-register", {})
    assert status == 400
    assert answer["error"]["code"] == "malformed_body"


def test_a_malformed_body_is_refused_before_the_store_is_opened(boot, monkeypatch) -> None:
    """A refused body writes nothing and reads nothing — with a store that
    is genuinely unreachable, a *malformed* ask still answers 400 rather
    than the store's refusal: the body is the caller's fault and is
    decided before any database is touched."""
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")
    server = boot(create_app())
    status, _, body = _post(
        server,
        "/promotion/pre-register",
        {"node_id": "not-a-uuid", "epoch_id": "e", "criteria": _CRITERIA},
    )
    assert status == 400
    assert body["error"]["class"] == "MalformedRequestError"


# -- The route's own transport laws --------------------------------------------------


def test_the_code_words_are_the_members_own() -> None:
    """The two code words the transport's doors answer with are the
    promotion member's own greppable words — restated in the transport
    so its doors can spell them before any member is importable, and
    pinned here so the restatement cannot drift from what the member's
    messages actually open with.

    The same agreement discipline :mod:`nullius_api.routes`' own suite
    applies to the members' route constants: a literal spelled twice is
    only safe while something checks the two spellings agree.
    """
    from promotion import errors

    assert PROMOTION_CONFLICT_CODE == errors.PROMOTION_CONFLICT_ERROR_CODE
    assert PROMOTION_PARENT_ABSENT_CODE == errors.PROMOTION_PARENT_ABSENT_ERROR_CODE


def test_the_route_is_served_not_501(seeded, boot) -> None:
    """Before this feature landed the route was declared in the table but
    carried no adapter and answered ``route_not_implemented``; the tests
    above prove it now serves the member's own act."""
    report, url = seeded
    node_id = _insert_node(url, campaign_id=report.campaign_ids[-1])
    server = boot(create_app())
    status, _, body = _post(
        server,
        "/promotion/pre-register",
        {"node_id": node_id, "epoch_id": report.epoch_ids[1], "criteria": _CRITERIA},
    )
    assert status != 501
    assert body.get("error", {}).get("code") != "route_not_implemented"


def test_the_unconfigured_store_answers_503(boot, monkeypatch) -> None:
    """No ``DATABASE_URL`` composes no promotion store: the route answers
    the unconfigured refusal, which is a different fact from an empty
    registry holding no row for the node."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    server = boot(create_app())
    status, _, body = _post(
        server,
        "/promotion/pre-register",
        {
            "node_id": str(uuid.uuid4()),
            "epoch_id": "some-epoch",
            "criteria": _CRITERIA,
        },
    )
    assert status == 503
    assert body["error"]["code"] == "component_unconfigured"


def test_a_wrong_verb_answers_405_with_an_allow_header(seeded, boot) -> None:
    """The path serves POST alone; a GET is the transport's own refusal,
    stated with the verb the route does answer."""
    server = boot(create_app())
    connection = http.client.HTTPConnection(
        "127.0.0.1", server.server_address[1], timeout=10
    )
    try:
        connection.request("GET", "/promotion/pre-register")
        response = connection.getresponse()
        headers = {name.lower(): value for name, value in response.getheaders()}
        body = json.loads(response.read().decode("utf-8"))
    finally:
        connection.close()
    assert response.status == 405
    assert headers["allow"] == "POST"
    assert body["error"]["code"] == "method_not_allowed"


@pytest.mark.parametrize("status_code", [200, 201, 400, 409, 422])
def test_no_body_carries_a_traceback_or_a_filesystem_path(
    seeded, boot, tmp_path, status_code: int
) -> None:
    """The envelope's last law, held on every door this route can answer
    through: no body names a stack or a path, whichever status it wears.

    The 503 door is checked the same way in its own test below (it needs a
    server composed with no store at all, which is a different fixture)."""
    report, url = seeded
    known = _insert_node(url, campaign_id=report.campaign_ids[-1])
    _standing_registration(url, known, report.epoch_ids[1], _CRITERIA)
    server = boot(create_app())

    asks = {
        200: {
            "node_id": known,
            "epoch_id": report.epoch_ids[1],
            "criteria": _CRITERIA,
        },
        201: {
            "node_id": _insert_node(url, campaign_id=report.campaign_ids[-1]),
            "epoch_id": report.epoch_ids[1],
            "criteria": _CRITERIA,
        },
        400: {"node_id": "not-a-uuid", "epoch_id": "e", "criteria": _CRITERIA},
        409: {
            "node_id": known,
            "epoch_id": report.epoch_ids[1],
            "criteria": _OTHER_CRITERIA,
        },
        422: {
            "node_id": str(uuid.uuid4()),
            "epoch_id": report.epoch_ids[1],
            "criteria": _CRITERIA,
        },
    }
    status, _, raw_body = _post(server, "/promotion/pre-register", asks[status_code])
    assert status == status_code
    text = json.dumps(raw_body)
    assert "Traceback" not in text
    assert str(tmp_path) not in text
    assert ".py" not in text


def test_an_unconfigured_body_leaks_no_traceback_or_path(boot, monkeypatch, tmp_path) -> None:
    """The 503 door's own body, checked the same way."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    server = boot(create_app())
    _, _, raw_body = _post(
        server,
        "/promotion/pre-register",
        {"node_id": str(uuid.uuid4()), "epoch_id": "e", "criteria": _CRITERIA},
    )
    text = json.dumps(raw_body)
    assert "Traceback" not in text
    assert str(tmp_path) not in text
    assert ".py" not in text


# -- The status is read off the member's flag, never invented ------------------------


@dataclass(frozen=True)
class _FakeRecord:
    """A record shaped like the member's — the fields the wire reads.

    A dataclass, because the codec spells a response by its fields: a
    bare object would be refused by the encoder and answered as an
    internal error, which is a different test entirely.
    """

    id: str
    node_id: str
    epoch_id: str
    criteria_hash: str
    pre_registered_at: str
    decided_at: str | None = None


@dataclass(frozen=True)
class _FakeResponse:
    """A response shaped like the member's: the flag, and the record.

    Used only by :class:`_UnreadableEndpoint` — the composition-fault
    case — because it is *not* the member's own response class and
    therefore may carry a ``created`` that is not a boolean.
    """

    created: Any
    record: Any


def _fake_record(node_id: str) -> _FakeRecord:
    return _FakeRecord(
        id=str(uuid.uuid4()),
        node_id=node_id,
        epoch_id="epoch",
        criteria_hash="a" * 64,
        pre_registered_at="2026-04-01T00:00:00+00:00",
    )


class _FakePreRegistrationStore:
    """A store shaped like feature 291's, answering a ``(record, created)`` pair.

    The real store is exercised by every other test in this file; this
    one exists so the *status* branch can be driven with the two flags
    directly, without manufacturing the store states that would produce
    them.  Its seam is the real one — the member's own endpoint wraps it
    and builds the response — so what the wire carries is still the
    member's own value.
    """

    def __init__(self, answer: Any) -> None:
        self._answer = answer
        self.asked: list[tuple] = []

    def pre_register(self, node_id, epoch_id, criteria, **kwargs):
        self.asked.append((node_id, epoch_id, criteria))
        return self._answer


class _UnreadableEndpoint:
    """An endpoint that answers a response with a non-boolean ``created``.

    A component that already speaks ``post`` passes through
    :func:`~nullius_api.routes.resolve_routes` unwrapped, which is how a
    response the transport cannot read can be driven without a member
    that would never compose one.
    """

    route = "/promotion/pre-register"

    def __init__(self, answer: Any) -> None:
        self._answer = answer

    def post(self, request):  # pragma: no cover - the answer is the point
        return self._answer


def _boot_with_promotion_component(boot, component: Any) -> ApiServer:
    from app.module_loader import Application

    return boot(Application(components={"promotion": component}, order=("promotion",)))


@pytest.mark.parametrize(("created", "expected"), [(True, 201), (False, 200)])
def test_the_status_is_the_members_own_created_flag(boot, created, expected) -> None:
    """One branch, one field: the flag the store answered with *is* the
    status, so a retry can never be served as a creation — and the
    response's own ``created`` reaches the wire unchanged."""
    node_id = str(uuid.uuid4())
    server = _boot_with_promotion_component(
        boot,
        _FakePreRegistrationStore((_fake_record(node_id), created)),
    )
    status, _, body = _post(
        server,
        "/promotion/pre-register",
        {"node_id": node_id, "epoch_id": "epoch", "criteria": _CRITERIA},
    )
    assert status == expected
    assert body["created"] is created
    assert body["record"]["node_id"] == node_id


def test_an_unreadable_response_is_a_composition_fault_not_a_status(boot) -> None:
    """A response whose ``created`` is not a boolean is refused internally
    — the transport will not invent a 201 for a record it cannot read —
    and the body stays the generic internal error with nothing echoed."""
    node_id = str(uuid.uuid4())
    server = _boot_with_promotion_component(
        boot,
        _UnreadableEndpoint(
            _FakeResponse(created="yes", record=_fake_record(node_id))
        ),
    )
    status, _, body = _post(
        server,
        "/promotion/pre-register",
        {"node_id": node_id, "epoch_id": "epoch", "criteria": _CRITERIA},
    )
    assert status == 500
    assert body["error"]["code"] == "internal_error"
    assert "yes" not in json.dumps(body)


def test_the_adapter_passes_the_members_own_terms_to_the_store(boot) -> None:
    """The transport relays the body's three terms — the node, the epoch
    and the criteria document — and validates none of them a second time:
    the store is reached exactly once, with exactly what was posted."""
    node_id = str(uuid.uuid4())
    store = _FakePreRegistrationStore((_fake_record(node_id), True))
    server = _boot_with_promotion_component(boot, store)
    _post(
        server,
        "/promotion/pre-register",
        {"node_id": node_id, "epoch_id": "epoch-1", "criteria": _CRITERIA},
    )
    assert len(store.asked) == 1
    asked_node, asked_epoch, asked_criteria = store.asked[0]
    assert asked_node == node_id
    assert asked_epoch == "epoch-1"
    assert asked_criteria.document() == _CRITERIA
