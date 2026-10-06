"""``GET /metrics/fdr-deploy``, ``GET /metrics/instrument-status`` and
``GET /metrics/regime-coverage`` over HTTP, and feature 6's four
gate-evidence routes beside them.

The three Observability routes features 341-343 expose in-process, held
to this build's own sentence: *System serves GET /metrics/fdr-deploy,
GET /metrics/instrument-status and GET /metrics/regime-coverage as
JSON, which returns 200 with null or empty fields when the store holds
no rows rather than a fabricated zero, and 503 with the code word for a
store failure.*  Feature 6 of additions_spec_operator_surfaces.xml adds
``GET /metrics/null-calibration``, ``/metrics/type-b-depth``,
``/metrics/discovery-rate`` and ``/metrics/meta-overfit`` under the
same sentence, over four stores and endpoints that are ``ops.gate_evidence``'s
own (already held to their own law in ``packages/ops/tests``); this
member's own footprint is only the HTTP wiring
(:data:`nullius_api.routes.API_ROUTES`, :data:`nullius_api.server.HTTP_ADAPTERS`),
so the section below drives all four through the real composed server
over a store this suite populates itself.

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
  ``history: []`` (never ``fdr_deploy: 0.0``), a rail whose every lamp —
  canary included — answers ``None`` rather than a fabricated bit when
  there is nothing to report (the canary has never run, so there is no
  reading to claim "replay is deterministic" with), and ``strata: []``
  (never a zero for a stratum nobody has named).
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

import dataclasses
import http.client
import json
import threading
import uuid
from typing import Any

import ops
import pytest
from conftest import TEST_TOKENS, token_for
from nullius_api import ApiServer
from nullius_api.demo import seed_demo_store

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
    nobody measured.

    The top-line reads are present and ``None``, never merely absent: an
    operator reading the body must be told *no campaign has closed* by the
    same keys a populated deployment is read off, the discipline
    :class:`~ops.fdr_route.FdrDeployResponse` states for its own ``None``.
    """
    server = boot(create_app())
    status, headers, body = _get(server, "/metrics/fdr-deploy")
    assert status == 200
    assert headers["content-type"] == "application/json"
    assert body["history"] == []
    assert body == {
        "history": [],
        "campaign_id": None,
        "fdr_deploy": None,
        "computed_at": None,
    }


def test_instrument_status_over_an_empty_store_answers_the_honest_absence(
    boot, test_database_url: str
) -> None:
    """A fresh database's rail: the canary has never run, so there is no
    reading to report — ``None``, the same honest absence the KS guard
    and ingest lamps answer for nothing yet measured, never a lit or dark
    lamp nobody checked."""
    server = boot(create_app())
    status, _, body = _get(server, "/metrics/instrument-status")
    assert status == 200
    assert body["canary"] is None
    assert body["canary_last_run_at"] is None
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
    assert body["strata"] == []
    # §C7's own shape beside the rows it came from: an empty ledger is an
    # empty *object*, not an absent key and not a zero.
    assert body["counts"] == {}


# -- The derived reads ride beside the fields ---------------------------------------
#
# The members state a response's derived figures as properties over its
# fields, precisely so a derived read cannot drift from what it is drawn
# from — so the body a caller parses must carry them, under the names the
# member's own docstring uses.  These three cases are the recorded defect:
# before the fix each body was the raw dataclass fields alone.


def test_fdr_deploy_carries_the_newest_campaigns_top_line_reads(
    boot, test_database_url: str
) -> None:
    """J8 step 1: ``fdr_deploy``, ``campaign_id`` and ``computed_at`` for
    the newest campaign, beside the ``history`` they are drawn from.

    The figure is the *newest* row's — the one §16 puts at the top line —
    and it is read off the response's own property rather than re-derived
    from the history here: a test that unpacked the trend itself would
    pass even if the body omitted the key."""
    seed_demo_store(test_database_url)
    server = boot(create_app())
    status, _, body = _get(server, "/metrics/fdr-deploy")
    assert status == 200
    assert body["history"], "the demo store closes three campaigns"
    newest_campaign, newest_figure, newest_instant = body["history"][-1]
    assert body["campaign_id"] == newest_campaign
    assert body["fdr_deploy"] == newest_figure
    assert body["computed_at"] == newest_instant
    # Never a fabricated 0.0 standing in for a figure nobody measured.
    assert isinstance(body["fdr_deploy"], float)


def test_regime_coverage_carries_the_counts_as_a_stratum_keyed_object(
    boot, test_database_url: str
) -> None:
    """J8 step 3: ``{stratum: count}`` — the ledger's own shape, keyed by
    stratum rather than a list of pairs a caller has to fold itself.

    ``strata`` stays beside it (the rows the mapping was derived from),
    and the two agree: the mapping is a view over the pairs, never a
    second answer."""
    seed_demo_store(test_database_url)
    server = boot(create_app())
    status, _, body = _get(server, "/metrics/regime-coverage")
    assert status == 200
    counts = body["counts"]
    assert isinstance(counts, dict), f"expected an object, got {counts!r}"
    assert counts == {stratum: count for stratum, count in body["strata"]}
    # A stratum the census counted and found empty stays present at 0 —
    # never dropped, never confused with a stratum nobody named.
    assert counts["crash"] == 0


def test_regime_coverage_never_folds_an_absent_stratum_into_a_zero(
    boot, test_database_url: str
) -> None:
    """The mapping distinguishes §C7's two states: a stratum present at
    ``0`` was counted and found empty; one absent from the mapping was
    never named.  A body that defaulted every stratum of the vocabulary
    into the object would erase the difference feature 286's warning
    fires on."""
    seed_demo_store(test_database_url)
    server = boot(create_app())
    _, _, body = _get(server, "/metrics/regime-coverage")
    named = set(body["counts"])
    assert named == {stratum for stratum, _count in body["strata"]}


# -- 503, member_refusal: a store failure is surfaced, never answered around ---------


@pytest.mark.parametrize(
    "path,expected_class",
    [
        ("/metrics/fdr-deploy", "FdrDeployMetricError"),
        ("/metrics/instrument-status", "InstrumentStatusError"),
        ("/metrics/regime-coverage", "RegimeCoverageMetricError"),
        ("/metrics/null-calibration", "GateEvidenceMetricError"),
        ("/metrics/type-b-depth", "GateEvidenceMetricError"),
        ("/metrics/discovery-rate", "GateEvidenceMetricError"),
        ("/metrics/meta-overfit", "GateEvidenceMetricError"),
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


# -- Feature 6's four gate-evidence routes --------------------------------------------
#
# additions_spec_operator_surfaces.xml feature 6: GET /metrics/null-calibration,
# /metrics/type-b-depth, /metrics/discovery-rate and /metrics/meta-overfit. The
# four stores and endpoints these routes read are ops.gate_evidence's own,
# already held to their law in packages/ops/tests; what this transport's own
# footprint adds is the HTTP wiring (the API_ROUTES rows and HTTP_ADAPTERS
# entries), so this suite drives each route through the real composed server
# on an ephemeral port over a store this test populated itself — the one way
# to prove a real row (not a fake endpoint) reaches the wire through
# json_encoding, with no traceback, exactly as the three Observability routes
# above are already proven.

GATE_EVIDENCE_ROUTES: tuple[str, ...] = (
    "/metrics/null-calibration",
    "/metrics/type-b-depth",
    "/metrics/discovery-rate",
    "/metrics/meta-overfit",
)


def _seed_gate_evidence_stores() -> dict[str, Any]:
    """Record one row into each of feature 6's four stores, resolved
    against this test's own isolated ``DATABASE_URL`` — and return the
    row each store answered, keyed by the route that reads it back.

    Seeded through the stores' own public ``record()``, exactly as a
    closed-out campaign or cycle would write it, never a direct table
    write: this suite's whole concern is the four *routes*, and seeding
    any other way could pass even if the route read the wrong table.
    """
    campaign_id = str(uuid.uuid4())
    iteration_id = str(uuid.uuid4())
    return {
        "/metrics/null-calibration": ops.NullCalibrations.resolve().record(
            campaign_id, sensitivity=0.8, specificity=0.9
        ),
        "/metrics/type-b-depth": ops.TypeBDepths.resolve().record(
            campaign_id, depth_past_flip_errors=3
        ),
        "/metrics/discovery-rate": ops.DiscoveryRates.resolve().record(
            campaign_id,
            discoveries=5,
            budget_charging_trials=100,
            ledger_trials=120,
        ),
        "/metrics/meta-overfit": ops.MetaOverfitGaps.resolve().record(
            iteration_id,
            train_mean=0.6,
            holdout_mean=0.55,
            train_worlds=10,
            holdout_worlds=10,
        ),
    }


@pytest.mark.parametrize("path", GATE_EVIDENCE_ROUTES)
def test_gate_evidence_route_answers_the_seeded_row_over_the_real_server(
    boot, test_database_url: str, path: str
) -> None:
    """Each of feature 6's four routes, driven through the real,
    composed server on port 0 (``boot`` binds ``("127.0.0.1", 0)``)
    over a store this test populated: 200, the seeded row as
    ``newest`` beside the one-row ``history`` it is drawn from, and a
    body that reached the wire through :mod:`nullius_api.json_encoding`
    rather than around it — every field the seeded row carries present
    and unchanged, and no traceback.
    """
    rows = _seed_gate_evidence_stores()
    server = boot(create_app())
    status, headers, body = _get(server, path)
    assert status == 200
    assert headers["content-type"] == "application/json"
    assert len(body["history"]) == 1
    assert body["newest"] is not None
    expected = rows[path]
    for field in dataclasses.fields(expected):
        assert body["newest"][field.name] == getattr(expected, field.name)
    assert body["history"][0] == body["newest"]
    text = json.dumps(body)
    assert "Traceback" not in text
    assert ".py" not in text


def test_gate_evidence_route_over_an_empty_store_answers_the_honest_absence(
    boot, test_database_url: str
) -> None:
    """A deployment that has closed no campaign or cycle out answers an
    empty history and a ``newest`` of ``None`` — never a fabricated
    zero standing in for a measurement nobody made."""
    server = boot(create_app())
    for path in GATE_EVIDENCE_ROUTES:
        status, _, body = _get(server, path)
        assert status == 200
        assert body["history"] == []
        assert body["newest"] is None
