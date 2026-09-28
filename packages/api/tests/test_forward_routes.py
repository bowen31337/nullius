"""``POST /forward/promote`` and ``GET /forward/decay`` over HTTP.

The two routes feature 332 and feature 334 name, held to this build's own
sentence: *System serves POST /forward/promote and GET /forward/decay as
JSON, which returns 404 for a node with no forward record or no observation
yet and 503 only for a store failure.*

Three clauses, each its own section below:

* **served as JSON, not 501** — before this feature landed,
  ``POST /forward/promote`` was declared in the route table (so its verb and
  its component resolved) but carried no adapter, and answered
  ``route_not_implemented``.  The tests in the first section prove the
  adapter now serves the member's own act: a fresh promotion opens the row,
  a retry answers the standing one, and a malformed body is refused before
  the store is ever opened.
* **404 for a node with no forward record or no observation yet** — both
  routes can reach :class:`~forward.errors.ForwardAbsentError`, the
  *decidable* half of the store's vocabulary (its own docstring: "the HTTP
  layer these features are for turns exactly this difference into a 404
  against a 503").  The absence is a state of the world — the promote step
  never ran, or the observation job has not, or (on ``POST
  /forward/promote`` itself) the promotion names a node the tree does not
  hold — and none of the three is a database fault.
* **503 only for a store failure** — rows a hand reached past the store to
  write (two promotion instants for one signal), a promotion with no
  instant to open at, and an unconfigured component all answer 503, and the
  tests below prove the *absence* face never leaks into that door: an
  unobserved record must not read as a broken database, and a broken
  database must not read as a state the pipeline will resolve on its own.

The suite composes the real application (``create_app()``) over a real
sqlite store — through :func:`nullius_api.demo.seed_demo_store` for the
common "promoted and observed" fixture and through the members' own public
seams (``promotion.PreRegistrations``, ``promotion.record_decision``,
``forward.forward_record``, ``forward.forward_observation``) for the
narrower states a route's refusal needs — never through a second, private
spelling of a row a member already owns.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import http.client
import json
import sqlite3
import threading
import uuid
from typing import Any
from urllib.parse import unquote, urlparse

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


# -- Seeding the states a route's refusal needs -------------------------------------

_FORWARD_DAYS = 90

_CRITERIA_KWARGS = {
    "theta": 0.3,
    "alpha": 0.05,
    "max_fdr_deploy": 0.25,
    "min_worlds": 50,
    "min_coverage_strata": 3,
    "min_forward_days": _FORWARD_DAYS,
}


def _sqlite_path(database_url: str) -> str:
    """Translate ``sqlite:///…`` the same way every store in this workspace
    does — restated here rather than imported, because a caller outside the
    member never reaches into its private helpers."""
    return unquote(urlparse(database_url).path).removeprefix("/")


def _insert_node(url: str, *, campaign_id: str) -> str:
    """A second ``node`` row, direct — the same shape
    :mod:`nullius_api.demo` inserts, for a node this suite promotes on its
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


def _pre_registered(url: str, node_id: str, epoch_id: str) -> None:
    import promotion

    criteria = promotion.PromotionCriteria(**_CRITERIA_KWARGS)
    promotion.PreRegistrations(url).pre_register(
        node_id,
        epoch_id,
        criteria,
        pre_registered_at=dt.datetime(2026, 4, 1, tzinfo=dt.UTC),
    )


def _decided(url: str, node_id: str) -> None:
    import promotion

    promotion.record_decision(
        node_id, decided_at=dt.datetime(2026, 4, 1, 1, tzinfo=dt.UTC), database_url=url
    )


def _promoted_but_unobserved_node(url: str, *, campaign_id: str, epoch_id: str) -> str:
    """A node with a forward record and *no* observation on it — the second
    face :class:`~forward.errors.ForwardAbsentError` names."""
    import forward

    node_id = _insert_node(url, campaign_id=campaign_id)
    _pre_registered(url, node_id, epoch_id)
    _decided(url, node_id)
    forward.forward_record(node_id, forward_days=_FORWARD_DAYS, database_url=url)
    return node_id


def _pre_registered_but_undecided_node(url: str, *, campaign_id: str, epoch_id: str) -> str:
    """A node whose promotion has no instant yet — feature 300's *open* row."""
    node_id = _insert_node(url, campaign_id=campaign_id)
    _pre_registered(url, node_id, epoch_id)
    return node_id


def _decided_promotion_over_a_vanished_node(url: str, *, campaign_id: str, epoch_id: str) -> str:
    """A promotion with a real instant to open at, whose node the ``node``
    table no longer holds — the third face of
    :class:`~forward.errors.ForwardAbsentError`
    (:meth:`forward.record.ForwardRecords.open_record`'s own docstring: *"the
    promotion names a node the node table does not hold"*).

    Reaching this state honestly needs the promotion decided first —
    ``open_record`` reads the promotion instant *before* it checks the node
    row exists — so the node is inserted, promoted normally, and then
    deleted through a connection that never turns ``PRAGMA foreign_keys``
    on, the one way SQLite allows a row's own children to outlive it.
    """
    node_id = _insert_node(url, campaign_id=campaign_id)
    _pre_registered(url, node_id, epoch_id)
    _decided(url, node_id)
    connection = sqlite3.connect(_sqlite_path(url))
    try:
        with connection:
            connection.execute("DELETE FROM node WHERE id = ?", (node_id,))
    finally:
        connection.close()
    return node_id


def _fork_a_second_vintage(url: str, node_id: str) -> None:
    """Reach past every store in this member and write a second
    ``promoted_at`` for a node that already holds a record — the one state
    no retry repairs, and the only state this suite answers 503 for that
    is not the unconfigured-component door."""
    connection = sqlite3.connect(_sqlite_path(url))
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        with connection:
            connection.execute(
                "INSERT INTO forward_record "
                "(id, node_id, promoted_at, observed_on) VALUES (?, ?, ?, ?)",
                (
                    str(uuid.uuid4()),
                    node_id,
                    "2099-01-01T00:00:00+00:00",
                    "2099-01-01",
                ),
            )
    finally:
        connection.close()


@pytest.fixture
def seeded(test_database_url: str):
    """The demo store: a fully promoted, observed node beside its campaigns
    and epochs — the common fixture every test below builds on."""
    report = seed_demo_store(test_database_url)
    return report, test_database_url


# -- POST /forward/promote: served, not 501 ------------------------------------------


def test_a_fresh_promotion_answers_200_with_created_true(seeded, boot) -> None:
    report, url = seeded
    node_id = _promoted_but_unobserved_node(
        url, campaign_id=report.campaign_ids[-1], epoch_id=report.epoch_ids[1]
    )
    # Undo the record this helper already opened, so the POST below is the
    # one that opens it — reaching past the store the same way the fixture
    # above does, since no member exposes "close a record" (there is
    # nothing to reopen from).
    connection = sqlite3.connect(_sqlite_path(url))
    try:
        with connection:
            connection.execute("DELETE FROM forward_record WHERE node_id = ?", (node_id,))
    finally:
        connection.close()

    server = boot(create_app())
    status, headers, body = _post(
        server, "/forward/promote", {"node_id": node_id, "forward_days": _FORWARD_DAYS}
    )
    assert status == 200
    assert headers["content-type"] == "application/json"
    assert body["created"] is True
    assert body["record"]["node_id"] == node_id
    assert body["record"]["live_ic"] is None


def test_a_retried_promotion_answers_200_with_created_false(seeded, boot) -> None:
    """The demo seed already opened ``report.node_id``'s record — so the
    first POST this test makes is itself a retry, and the standing row
    comes back rather than a second one being opened (feature 332's
    one-signal law)."""
    report, _ = seeded
    server = boot(create_app())
    status, _, body = _post(
        server,
        "/forward/promote",
        {"node_id": report.node_id, "forward_days": _FORWARD_DAYS},
    )
    assert status == 200
    assert body["created"] is False
    assert body["record"]["node_id"] == report.node_id


@pytest.mark.parametrize(
    "overrides",
    [
        {"node_id": "not-a-uuid"},
        {"forward_days": None},
        {"forward_days": 0},
        {"forward_days": -5},
        {"forward_days": True},
        {"forward_days": 1.5},
    ],
)
def test_a_malformed_body_answers_400(seeded, boot, overrides: dict) -> None:
    report, _ = seeded
    body = {"node_id": report.node_id, "forward_days": _FORWARD_DAYS}
    body.update(overrides)
    server = boot(create_app())
    status, _, answer = _post(server, "/forward/promote", body)
    assert status == 400
    assert answer["error"]["code"] == "malformed_body"


def test_a_missing_body_answers_400(seeded, boot) -> None:
    server = boot(create_app())
    status, _, answer = _post(server, "/forward/promote", {})
    assert status == 400
    assert answer["error"]["code"] == "malformed_body"


def test_no_promotion_instant_answers_503(seeded, boot) -> None:
    """A node that was pre-registered but never decided has no instant to
    open a record against — feature 300's own refusal, translated to
    ``ForwardPromotionError`` and answered 503, never 404: the pipeline is
    unfinished, not the world stating an absence."""
    report, url = seeded
    node_id = _pre_registered_but_undecided_node(
        url, campaign_id=report.campaign_ids[-1], epoch_id=report.epoch_ids[1]
    )
    server = boot(create_app())
    status, _, body = _post(
        server, "/forward/promote", {"node_id": node_id, "forward_days": _FORWARD_DAYS}
    )
    assert status == 503
    assert body["error"]["code"] == "member_refusal"
    assert body["error"]["class"] == "ForwardPromotionError"


def test_a_decided_promotion_over_a_vanished_node_answers_404(seeded, boot) -> None:
    """The promotion names a node the ``node`` table does not hold — the
    third face of :class:`~forward.errors.ForwardAbsentError`, answered 404
    rather than the generic member-refusal 503."""
    report, url = seeded
    node_id = _decided_promotion_over_a_vanished_node(
        url, campaign_id=report.campaign_ids[-1], epoch_id=report.epoch_ids[1]
    )
    server = boot(create_app())
    status, _, body = _post(
        server,
        "/forward/promote",
        {"node_id": node_id, "forward_days": _FORWARD_DAYS},
    )
    assert status == 404
    assert body["error"]["code"] == "forward_record_absent"
    assert body["error"]["class"] == "ForwardAbsentError"


def test_an_unregistered_node_answers_503_not_404(seeded, boot) -> None:
    """A node nobody pre-registered has no promotion instant to open a
    record against — ``open_record`` reads that instant *before* it ever
    checks whether the node row exists, so this is
    ``ForwardPromotionError`` (503), never the absence class."""
    _, _ = seeded
    server = boot(create_app())
    status, _, body = _post(
        server,
        "/forward/promote",
        {"node_id": str(uuid.uuid4()), "forward_days": _FORWARD_DAYS},
    )
    assert status == 503
    assert body["error"]["code"] == "member_refusal"
    assert body["error"]["class"] == "ForwardPromotionError"


def test_promote_unconfigured_store_answers_503(boot, monkeypatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    server = boot(create_app())
    status, _, body = _post(
        server,
        "/forward/promote",
        {"node_id": str(uuid.uuid4()), "forward_days": _FORWARD_DAYS},
    )
    assert status == 503
    assert body["error"]["code"] == "component_unconfigured"


# -- GET /forward/decay: 200, then the 404/503 split ---------------------------------


def test_the_observed_curve_answers_200(seeded, boot) -> None:
    report, _ = seeded
    server = boot(create_app())
    status, headers, body = _get(server, f"/forward/decay?node_id={report.node_id}")
    assert status == 200
    assert headers["content-type"] == "application/json"
    assert body["node_id"] == report.node_id
    # ``observed_days`` is a derived property, not a dataclass field, so the
    # codec (which spells a dataclass by its fields alone) never puts it on
    # the wire — the count is read off the points the wire does carry.
    assert len(body["points"]) == 2
    assert [point["days"] for point in body["points"]] == sorted(
        point["days"] for point in body["points"]
    )


def test_a_node_with_no_forward_record_answers_404(seeded, boot) -> None:
    _, _ = seeded
    server = boot(create_app())
    status, _, body = _get(server, f"/forward/decay?node_id={uuid.uuid4()}")
    assert status == 404
    assert body["error"]["code"] == "forward_record_absent"
    assert body["error"]["class"] == "ForwardAbsentError"


def test_a_promoted_but_unobserved_node_answers_404(seeded, boot) -> None:
    report, url = seeded
    node_id = _promoted_but_unobserved_node(
        url, campaign_id=report.campaign_ids[-1], epoch_id=report.epoch_ids[1]
    )
    server = boot(create_app())
    status, _, body = _get(server, f"/forward/decay?node_id={node_id}")
    assert status == 404
    assert body["error"]["code"] == "forward_record_absent"
    assert body["error"]["class"] == "ForwardAbsentError"
    assert node_id in body["error"]["message"]


def test_a_two_vintage_row_answers_503_not_404(seeded, boot) -> None:
    """The one store fault this suite can manufacture without touching a
    file: rows a hand reached past the member to write.  This must answer
    503 — the class is the store's own, never the absence class, so a
    genuinely broken record is never told apart from a healthy but young
    one by the wrong status."""
    report, url = seeded
    _fork_a_second_vintage(url, report.node_id)
    server = boot(create_app())
    status, _, body = _get(server, f"/forward/decay?node_id={report.node_id}")
    assert status == 503
    assert body["error"]["code"] == "member_refusal"
    assert body["error"]["class"] == "ForwardStoreError"


def test_decay_unconfigured_store_answers_503(boot, monkeypatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    server = boot(create_app())
    status, _, body = _get(server, f"/forward/decay?node_id={uuid.uuid4()}")
    assert status == 503
    assert body["error"]["code"] == "component_unconfigured"
    assert body["error"]["class"] != "ForwardAbsentError"


def test_the_decay_absence_leaks_no_traceback_or_filesystem_path(
    seeded, boot, tmp_path
) -> None:
    _, _ = seeded
    server = boot(create_app())
    status, _, raw_body = _get(server, f"/forward/decay?node_id={uuid.uuid4()}")
    assert status == 404
    text = json.dumps(raw_body)
    assert "Traceback" not in text
    assert str(tmp_path) not in text
    assert ".py" not in text


def test_the_promote_absence_leaks_no_traceback_or_filesystem_path(
    seeded, boot, tmp_path
) -> None:
    report, url = seeded
    node_id = _decided_promotion_over_a_vanished_node(
        url, campaign_id=report.campaign_ids[-1], epoch_id=report.epoch_ids[1]
    )
    server = boot(create_app())
    status, _, raw_body = _post(
        server, "/forward/promote", {"node_id": node_id, "forward_days": _FORWARD_DAYS}
    )
    assert status == 404
    text = json.dumps(raw_body)
    assert "Traceback" not in text
    assert str(tmp_path) not in text
    assert ".py" not in text
