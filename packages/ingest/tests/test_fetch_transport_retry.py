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


def test_archive_fetch_percent_encodes_a_non_ascii_symbol(monkeypatch):
    # Binance lists symbols such as 牛来USDT; http.client sends the request
    # line as ASCII, so an unencoded path raised UnicodeEncodeError, which no
    # per-day handler caught, and the whole metrics run died at that symbol.
    import io
    import typing
    import urllib.request

    from nullius_ingest.bars_backfill import urllib_archive_fetch

    sent: list[str] = []

    class _Response(io.BytesIO):
        status = 200
        headers: typing.ClassVar[dict[str, str]] = {}

    def fake_urlopen(request, timeout):
        sent.append(request.full_url)
        return _Response(b"zip")

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    base = "https://data.binance.vision/data/futures/um/daily/metrics/"
    assert urllib_archive_fetch(f"{base}牛来USDT/牛来USDT-metrics-2026-10-14.zip").body == b"zip"
    assert sent[-1] == (
        f"{base}%E7%89%9B%E6%9D%A5USDT/%E7%89%9B%E6%9D%A5USDT-metrics-2026-10-14.zip"
    )
    sent[-1].encode("ascii")

    # An ASCII URL, query and existing escapes included, is sent unchanged.
    ascii_url = "https://s3.example/?delimiter=/&prefix=data%2Fx/BTCUSDT-1d-2024-01.zip"
    urllib_archive_fetch(ascii_url)
    assert sent[-1] == ascii_url
