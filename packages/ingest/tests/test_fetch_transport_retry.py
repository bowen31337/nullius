"""A transport failure (dropped socket, reset, timeout) is retried, then
refused as a BarsBackfillError for that request only, never escaping as a
raw exception that kills a whole backfill run."""

from __future__ import annotations

import http.client

import pytest
from nullius_ingest.bars_backfill import (
    MAX_RETRIES,
    BarsBackfillError,
    HttpResponse,
    _request_archive,
    _request_json,
)


def _flaky(failures: int, exc: BaseException, ok: HttpResponse):
    calls = {"n": 0}

    def call(*_args):
        calls["n"] += 1
        if calls["n"] <= failures:
            raise exc
        return ok

    return call, calls


def test_archive_retries_remote_disconnect_then_succeeds():
    ok = HttpResponse(status=200, headers={}, body=b"zip")
    fetch, calls = _flaky(2, http.client.RemoteDisconnected("closed"), ok)
    sleeps: list[float] = []
    assert _request_archive(fetch, "u", sleep=sleeps.append, what="f.zip") is ok
    assert calls["n"] == 3
    assert [s for s in sleeps if s >= 1.0] == [1.0, 2.0]


def test_json_retries_timeout_then_succeeds():
    ok = HttpResponse(status=200, headers={}, body=b"[1]")
    fetch, calls = _flaky(1, TimeoutError("timed out"), ok)
    assert _request_json(fetch, "/p", {}, sleep=lambda _s: None, what="klines") == [1]
    assert calls["n"] == 2


def test_persistent_transport_failure_is_a_backfill_error():
    ok = HttpResponse(status=200, headers={}, body=b"")
    fetch, calls = _flaky(10**6, ConnectionResetError("reset"), ok)
    with pytest.raises(BarsBackfillError, match="transport failure"):
        _request_archive(fetch, "u", sleep=lambda _s: None, what="f.zip")
    assert calls["n"] == MAX_RETRIES + 1


def test_incomplete_read_is_retried():
    ok = HttpResponse(status=200, headers={}, body=b"zip")
    fetch, _ = _flaky(1, http.client.IncompleteRead(b"", 10), ok)
    assert _request_archive(fetch, "u", sleep=lambda _s: None, what="f.zip") is ok
