"""The archive listing parsers accept non-ASCII symbol names.

Binance lists USDT symbols named in Chinese (牛来USDT, 币安人生USDT, ...), and
the S3 listing returns their keys as raw UTF-8. An ASCII-only symbol pattern
silently dropped them from spot ``--top N`` discovery and from UM perpetual
discovery. Dated delivery contracts (``BTCUSDT_250926``) and settled ones
(``ICPUSDT_SETTLED``) are not perpetuals and stay excluded by the pattern
itself, not only by the USDT-suffix check after it.
"""

from __future__ import annotations

from nullius_ingest.bars_backfill import (
    ARCHIVE_KLINES_PREFIX,
    HttpResponse,
    _list_archive_months,
)
from nullius_ingest.derivs_backfill import (
    _UM_KLINES_PREFIX,
    _UM_KLINES_SYMBOL_RE,
)


def _listing(keys: list[str]):
    contents = "".join(
        f"<Contents><Key>{key}</Key></Contents><Contents><Key>{key}.CHECKSUM</Key></Contents>"
        for key in keys
    )
    body = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<ListBucketResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/">'
        f"{contents}<IsTruncated>false</IsTruncated></ListBucketResult>"
    ).encode()
    return lambda _url: HttpResponse(status=200, headers={}, body=body)


def _keys(prefix: str, folders: list[str]) -> list[str]:
    return [f"{prefix}{name}/1d/{name}-1d-2026-08.zip" for name in folders]


def test_spot_listing_keeps_a_non_ascii_usdt_symbol():
    fetch = _listing(
        _keys(ARCHIVE_KLINES_PREFIX, ["BTCUSDT", "牛来USDT", "币安人生USDT", "币安人生USDC"])
    )
    months = _list_archive_months(fetch, sleep=lambda _s: None)
    assert sorted(months) == sorted(["BTCUSDT", "牛来USDT", "币安人生USDT"])


def test_um_listing_keeps_non_ascii_perps_and_drops_delivery_contracts():
    fetch = _listing(
        _keys(
            _UM_KLINES_PREFIX,
            ["BTCUSDT", "1000PEPEUSDT", "龙虾USDT", "我踏马来了USDT",
             "BTCUSDT_250926", "ICPUSDT_SETTLED"],
        )
    )
    months = _list_archive_months(
        fetch, sleep=lambda _s: None, prefix=_UM_KLINES_PREFIX, key_re=_UM_KLINES_SYMBOL_RE
    )
    assert sorted(months) == sorted(["BTCUSDT", "1000PEPEUSDT", "龙虾USDT", "我踏马来了USDT"])


def test_patterns_reject_underscored_names_on_their_own():
    from nullius_ingest.bars_backfill import _ARCHIVE_KEY_RE

    for pattern, prefix in ((_ARCHIVE_KEY_RE, ARCHIVE_KLINES_PREFIX), (_UM_KLINES_SYMBOL_RE, _UM_KLINES_PREFIX)):
        for name in ("BTCUSDT_250926", "ICPUSDT_SETTLED", "btcusdt"):
            assert pattern.match(f"{prefix}{name}/1d/{name}-1d-2026-08.zip") is None, name
        assert pattern.match(f"{prefix}牛来USDT/1d/牛来USDT-1d-2026-08.zip") is not None
