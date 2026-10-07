"""Tests for :mod:`router.bingx_funding` and :meth:`BingXClient.income`.

``additions_spec_vst_fidelity.xml`` feature 4, held clause by clause:
*System saves the VST account's funding-fee income to a
router_funding_income table ... BingXClient.income(income_type, *,
start_ms=None, end_ms=None, limit=None) is a signed GET on
/openApi/swap/v2/user/income, returning the data list ...
router.bingx_funding.ingest_funding(client, store, *, since_ms) stores each
FUNDING_FEE row (symbol, income as Decimal text, asset, time, tranId),
idempotent on tranId, and returns the count of new rows.*

Every test injects a transport that answers the pinned
``income_funding_fee.json`` capture (or a scripted variant of it) — the
suite never opens a socket, and the fixture is the live VST account's own
answer, pinned rather than hand-written.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from router.bingx_client import (
    INCOME_PATH,
    VST_BASE_URL,
    BingXClient,
    RouterBingXRefusedError,
)
from router.bingx_funding import (
    BINGX_FUNDING_CODE,
    FUNDING_FEE_INCOME_TYPE,
    RouterBingXFundingError,
    RouterFundingIncomeStore,
    ingest_funding,
)
from router.errors import RouterStoreError

API_KEY = "vst-key-0123456789"
SECRET_KEY = "vst-secret-abcdef"
FIXED_MILLIS = 1_700_000_000_123

#: A window start comfortably before the pinned fixture's earliest row, so a
#: fetch narrowed to it would answer every row the fixture carries.
SINCE_MS = 1_791_200_000_000

LIVE_FIXTURES = Path(__file__).resolve().parent / "fixtures" / "bingx_vst" / "live"


def _pinned_income_bytes() -> bytes:
    """The live VST capture, exactly as the venue sent it."""
    return (LIVE_FIXTURES / "income_funding_fee.json").read_bytes()


def _pinned_income_rows() -> list[dict]:
    """The pinned capture's ``data`` list, decoded for assertions."""
    return json.loads(_pinned_income_bytes())["data"]


def _envelope(data: object, *, code: int = 0, msg: str = "") -> bytes:
    """A venue response body, as JSON bytes."""
    return json.dumps({"code": code, "msg": msg, "data": data}).encode("utf-8")


class _Recorder:
    """A transport that records every request and answers scripted responses.

    The suite's whole network stance: nothing here opens a socket, and the
    recorder keeps what it was handed so a test can assert the URL, the
    headers and the body before judging the answer.
    """

    def __init__(self, *answers: tuple[int, bytes]) -> None:
        self._answers = list(answers)
        self.requests: list[tuple[str, str, dict, bytes]] = []

    def __call__(self, method: str, url: str, headers, body):
        self.requests.append((method, url, dict(headers), bytes(body)))
        answer = self._answers.pop(0)
        return answer

    @property
    def last_url(self) -> str:
        return self.requests[-1][1]


def _client(recorder: _Recorder) -> BingXClient:
    """A client over the recorder with fake credentials and a pinned clock."""
    return BingXClient(
        api_key=API_KEY,
        secret_key=SECRET_KEY,
        transport=recorder,
        clock=lambda: FIXED_MILLIS,
    )


def _ingest(answer: tuple[int, bytes], store: RouterFundingIncomeStore, **kwargs) -> int:
    """Ingest through a fresh client scripted with one answer."""
    return ingest_funding(
        _client(_Recorder(answer)), store, since_ms=kwargs.pop("since_ms", SINCE_MS)
    )


@pytest.fixture
def store(test_database_url: str) -> RouterFundingIncomeStore:
    return RouterFundingIncomeStore(test_database_url)


# -- BingXClient.income --------------------------------------------------------


def test_income_is_a_signed_get_narrowed_to_incomeType_and_startTime() -> None:
    recorder = _Recorder((200, _pinned_income_bytes()))
    client = _client(recorder)

    data = client.income(FUNDING_FEE_INCOME_TYPE, start_ms=SINCE_MS)

    assert data == _pinned_income_rows()
    method, url, headers, body = recorder.requests[-1]
    assert method == "GET"
    assert url.startswith(f"{VST_BASE_URL}{INCOME_PATH}")
    assert "incomeType=FUNDING_FEE" in url
    assert f"startTime={SINCE_MS}" in url
    assert "signature=" in url
    assert headers["X-BX-APIKEY"] == API_KEY
    assert body == b""


def test_income_carries_end_ms_and_limit_when_given() -> None:
    recorder = _Recorder((200, _envelope([])))
    client = _client(recorder)

    client.income(FUNDING_FEE_INCOME_TYPE, start_ms=1, end_ms=2, limit=50)

    url = recorder.last_url
    assert "endTime=2" in url
    assert "limit=50" in url


def test_income_raises_the_clients_own_refusal_for_a_non_zero_code() -> None:
    recorder = _Recorder((200, _envelope(None, code=80001, msg="refused")))
    client = _client(recorder)

    with pytest.raises(RouterBingXRefusedError) as refusal:
        client.income(FUNDING_FEE_INCOME_TYPE, start_ms=SINCE_MS)
    assert refusal.value.code == 80001


# -- ingest_funding -------------------------------------------------------------


def test_ingest_funding_stores_every_pinned_row(
    store: RouterFundingIncomeStore,
) -> None:
    pinned = _pinned_income_rows()

    inserted = _ingest((200, _pinned_income_bytes()), store)

    assert inserted == len(pinned)
    stored = {row.tran_id: row for row in store.rows()}
    assert len(stored) == len(pinned)
    for payload in pinned:
        row = stored[payload["tranId"]]
        assert row.symbol == payload["symbol"]
        assert row.asset == payload["asset"]
        assert row.time == payload["time"]
        # The venue's own decimal text, never re-rendered.
        assert row.income == payload["income"]


def test_reingest_is_idempotent_on_tran_id(store: RouterFundingIncomeStore) -> None:
    pinned_bytes = _pinned_income_bytes()

    first = _ingest((200, pinned_bytes), store)
    second = _ingest((200, pinned_bytes), store)

    assert first == len(_pinned_income_rows())
    assert second == 0
    assert len(store.rows()) == len(_pinned_income_rows())


def test_rows_can_be_narrowed_to_one_symbol(store: RouterFundingIncomeStore) -> None:
    _ingest((200, _pinned_income_bytes()), store)

    expected = [row for row in _pinned_income_rows() if row["symbol"] == "BTC-USDT"]
    narrowed = store.rows(symbol="BTC-USDT")

    assert len(narrowed) == len(expected)
    assert all(row.symbol == "BTC-USDT" for row in narrowed)


def test_a_non_zero_code_is_refused_with_the_clients_existing_refusal(
    store: RouterFundingIncomeStore,
) -> None:
    with pytest.raises(RouterBingXRefusedError) as refusal:
        _ingest((200, _envelope(None, code=80001, msg="refused")), store)

    assert refusal.value.code == 80001
    # Nothing landed: the refusal happened before any row was ever read.
    assert store.rows() == ()


def test_a_malformed_row_is_refused_rather_than_silently_dropped(
    store: RouterFundingIncomeStore,
) -> None:
    malformed = dict(_pinned_income_rows()[0])
    del malformed["tranId"]

    with pytest.raises(RouterBingXFundingError) as refusal:
        _ingest((200, _envelope([malformed])), store)

    assert BINGX_FUNDING_CODE in str(refusal.value)
    assert store.rows() == ()


def test_a_row_of_a_different_income_type_is_skipped_not_stored(
    store: RouterFundingIncomeStore,
) -> None:
    pinned = _pinned_income_rows()
    commission = dict(pinned[0])
    commission["incomeType"] = "COMMISSION"
    commission["tranId"] = "not-a-funding-fee"

    inserted = _ingest((200, _envelope([commission, *pinned])), store)

    assert inserted == len(pinned)
    assert "not-a-funding-fee" not in {row.tran_id for row in store.rows()}


def test_a_row_that_is_not_an_object_is_refused(
    store: RouterFundingIncomeStore,
) -> None:
    with pytest.raises(RouterBingXFundingError):
        _ingest((200, _envelope(["not-an-object"])), store)
    assert store.rows() == ()


def test_a_client_with_no_income_method_is_refused(
    store: RouterFundingIncomeStore,
) -> None:
    class _NoIncome:
        pass

    with pytest.raises(RouterBingXFundingError):
        ingest_funding(_NoIncome(), store, since_ms=SINCE_MS)


# -- RouterFundingIncomeStore ---------------------------------------------------


class TestResolve:
    def test_resolves_from_database_url(self, test_database_url: str) -> None:
        resolved = RouterFundingIncomeStore.resolve()
        assert resolved is not None
        assert resolved.database_url == test_database_url

    @pytest.mark.parametrize("unset", [None, "", "   "])
    def test_no_database_url_resolves_to_none(self, unset: str | None) -> None:
        env = {} if unset is None else {"DATABASE_URL": unset}
        assert RouterFundingIncomeStore.resolve(env) is None

    def test_construction_rejects_a_blank_url(self) -> None:
        with pytest.raises(RouterStoreError):
            RouterFundingIncomeStore("   ")

    def test_a_non_sqlite_scheme_is_refused_as_an_address_fault(self) -> None:
        unreachable = RouterFundingIncomeStore("postgresql://host/nullius")
        with pytest.raises(RouterStoreError) as refusal:
            unreachable.rows()
        assert not isinstance(refusal.value, RouterBingXFundingError)
        assert "postgresql" in str(refusal.value)
