"""``GET /metrics/fdr-deploy``, ``GET /metrics/instrument-status`` and
``GET /metrics/regime-coverage`` over HTTP.

The three Observability routes features 341-343 expose in-process, held
to this build's own sentence: *System serves GET /metrics/fdr-deploy,
GET /metrics/instrument-status and GET /metrics/regime-coverage as
JSON, which returns 200 with null or empty fields when the store holds
no rows rather than a fabricated zero, and 503 with the code word for a
store failure.*

Two clauses, each its own section below, pinned through the real
composed application rather than a fake — the transport's own dispatch
laws (``member_refusal``, ``component_unconfigured``, the envelope) are
already pinned generically in ``test_server.py`` against a stand-in
endpoint; this suite is the one that proves the *real* per-campaign
figure, rail and ledger each reach the wire honestly, over the three
members that actually answer them (scoring, canary, nulloracle, regime,
and this member's own live-metrics store):

* **200 with null/empty fields, never a fabricated zero** — a freshly
  composed, empty database answers each route's own honest absence:
  ``history: []`` (never ``fdr_deploy: 0.0``), a rail whose only bit
  that can ever be true or false without a reading is ``canary`` (a halt
  table with no rows *is* "not halted", never an absence), and
  ``strata: []`` (never a zero for a stratum nobody has named).
* **503 with the ``member_refusal`` code word for a store failure** — a
  ``DATABASE_URL`` whose scheme none of the sibling stores can speak
  composes every route (composition only asks whether the variable is
  non-empty) but fails at the *first real read*: each store's own
  scheme validation (feature 267's, feature 143's, feature 284's) raises
  that member's typed error, translated at the ops seam into this
  member's own vocabulary and answered here as the transport's generic
  member refusal — never a fabricated figure standing in for a database
  nobody could open.

The suite composes the real application (``create_app()``) over a
per-test sqlite store from ``conftest.py``'s isolation fixture — no
fakes, no direct table writes, because the honest-absence and
store-failure laws these three routes exist to hold are exactly the
laws a fake endpoint could not misstate on the transport's behalf.
"""

from __future__ import annotations

import http.client
import json
import threading
from typing import Any

import pytest
from conftest import TEST_TOKENS, token_for
from nullius_api import ApiServer

from app.module_loader import create_app

# -- Booting the real, composed server -----------------------------------------------


class _Boot:
    """Boot one composed server per case on an ephemeral loopback port."""

    def __init__(self) -> None:
        self._servers: list[ApiServer] = []

    def __call__(self, application: Any = None) -> ApiServer:
        server = ApiServer(
            ("127.0.0.1", 0),
            application if application is not None else create_app(),
            TEST_TOKENS,
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


def _get(
    server: ApiServer, path: str, scope: str | None = "metrics:read"
) -> tuple[int, dict[str, str], Any]:
    """One GET, presenting ``scope``'s token (``None`` for no header).

    The metrics routes all want ``metrics:read``, so that is the default;
    the cases about the gate pass ``None`` or another scope.
    """
    headers = {} if scope is None else {"Authorization": f"Bearer {token_for(scope)}"}
    connection = http.client.HTTPConnection(
        "127.0.0.1", server.server_address[1], timeout=10
    )
    try:
        connection.request("GET", path, headers=headers)
        response = connection.getresponse()
        raw = response.read().decode("utf-8")
        headers = {name.lower(): value for name, value in response.getheaders()}
        return response.status, headers, (json.loads(raw) if raw else None)
    finally:
        connection.close()


# -- 200, honest absence: null and empty, never a fabricated zero --------------------


def test_fdr_deploy_over_an_empty_store_answers_the_honest_absence(
    boot, test_database_url: str
) -> None:
    """A deployment that has closed no campaign out answers an empty
    trend — never a top-line ``0.0``, which would be a projection
    nobody measured."""
    server = boot(create_app())
    status, headers, body = _get(server, "/metrics/fdr-deploy")
    assert status == 200
    assert headers["content-type"] == "application/json"
    assert body == {"history": []}


def test_instrument_status_over_an_empty_store_answers_the_honest_absence(
    boot, test_database_url: str
) -> None:
    """A fresh database's rail: canary is never absent (no halt row is
    *not halted*, a real bit), while the KS guard and ingest lamps —
    which have nothing to report yet — answer ``None``, never a lit or
    dark lamp nobody measured."""
    server = boot(create_app())
    status, _, body = _get(server, "/metrics/instrument-status")
    assert status == 200
    assert body["canary"] is True
    assert body["ks_guard"] is None
    assert body["ingest"] is None
    assert body["campaign"] is None
    assert body["ks_pvalue"] is None
    assert body["ingest_lag_seconds"] is None
    assert body["ingest_read_at"] is None


def test_regime_coverage_over_an_empty_store_answers_the_honest_absence(
    boot, test_database_url: str
) -> None:
    """A configured database where no census has run names no stratum
    — an empty mapping, never a zero stamped onto a stratum nobody
    counted."""
    server = boot(create_app())
    status, _, body = _get(server, "/metrics/regime-coverage")
    assert status == 200
    assert body == {"strata": []}


# -- 503, member_refusal: a store failure is surfaced, never answered around ---------


@pytest.mark.parametrize(
    "path,expected_class",
    [
        ("/metrics/fdr-deploy", "FdrDeployMetricError"),
        ("/metrics/instrument-status", "InstrumentStatusError"),
        ("/metrics/regime-coverage", "RegimeCoverageMetricError"),
    ],
)
def test_a_store_the_member_cannot_open_answers_503_member_refusal(
    boot, monkeypatch: pytest.MonkeyPatch, path: str, expected_class: str
) -> None:
    """``DATABASE_URL`` names a scheme none of the sibling stores can
    speak (feature 267's, 143's and 284's own stores each validate the
    scheme is ``sqlite`` before anything else) — a non-empty value, so
    every route still composes, but the *first real read* raises that
    member's own typed error.  Translated at the ops seam and answered
    here as the transport's generic ``member_refusal`` — the code word
    a store failure carries, never a fabricated figure standing in for
    a database nobody could open."""
    monkeypatch.setenv("DATABASE_URL", "postgresql://nowhere/unreachable")
    server = boot(create_app())
    status, _, body = _get(server, path)
    assert status == 503
    assert body["error"]["code"] == "member_refusal"
    assert body["error"]["class"] == expected_class


def test_no_store_failure_body_carries_a_traceback_or_a_filesystem_path(
    boot, monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """The envelope's last law, over this route family's own 503: no
    stack, no path — including this run's own temporary directory."""
    monkeypatch.setenv("DATABASE_URL", "postgresql://nowhere/unreachable")
    server = boot(create_app())
    _, _, body = _get(server, "/metrics/instrument-status")
    text = json.dumps(body)
    assert "Traceback" not in text
    assert str(tmp_path) not in text
    assert ".py" not in text
