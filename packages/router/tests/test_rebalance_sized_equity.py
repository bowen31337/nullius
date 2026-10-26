"""A slot sizes from the equity it read, not the book's fixed figure.

The defect this file pins — **VST-SIZING-1**, the execution deviation
shadow v1 Addendum 14 declares
(``docs/preregistration/2026-10-15-shadow-v1.ADDENDUM.md``) — is a
mis-sizing, not a refusal:

    A gross-1.0 book at ``equity_usdt`` 10000 sizes every target as
    ``equity × weight ÷ mark``, so holding the whole book needs 10000
    USDT of margin at the preflight's own leverage of one.  The live
    account answered a wallet of 10040 USDT and an equity of 9688.82,
    so the book's own figure is the *whole pool*: the 12:05 UTC slot of
    2026-10-26 placed its five position-reducing legs, admitted one
    increasing leg and deferred the other 47 (752.4 USDT of margin
    against 3.50 available), and every slot from 2026-10-22 had ended
    exit 1 the same way.

The repair is one re-stamp inside the slot: after the daily-loss guard has
read the account's equity — the *one* venue read of it the slot makes —
and before :func:`router.bingx_mirror.build_mirror_plan` is called, the
slot's own book carries

    sized = min(book equity_usdt, guard.current_equity) × utilisation

with ``utilisation`` read from ``BINGX_VST_MARGIN_UTILISATION`` (default
``0.90``).  The **same** mapping is handed to the plan, to the placement
and to the report, so the sizer and the fidelity recompute in
:mod:`router.bingx_mirror` see one figure; the book file, its weights and
the paper book are untouched.

The suite drives the command's own entry point with the module's injected
doubles — the recording client, store, clock and env the neighbouring
rebalance suite uses — and captures the ``book`` each step is handed, so
the assertion is on the operand rather than on a plan's arithmetic.  No
test opens a socket.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from router.bingx_mirror import (
    MIRROR_OUTCOME_PLACED,
    build_mirror_plan,
    mirror_place,
)
from router.bingx_rebalance import (
    BINGX_REBALANCE_CODE,
    DEFAULT_MARGIN_UTILISATION,
    EXIT_OK,
    EXIT_REFUSED,
    MARGIN_UTILISATION_ENV,
    RouterSlotCompletionStore,
    floor_to_slot,
    main,
)
from router.submission_result import RouterOrderPlacementStore

# The doubles this member's mirror suite already proves the placement path
# against, reused rather than re-written — the same import the neighbouring
# rebalance suite takes, for the same reason.
from test_bingx_mirror import (  # isort: skip
    _CountingLimiter,
    _MirrorClient,
    _book,
    _clock,
)

#: A moment inside the 12:00 slot; the slot's own start is 12:00.
MID_SLOT = datetime(2026, 10, 26, 12, 5, tzinfo=UTC)
SLOT_NOON = datetime(2026, 10, 26, 12, 0, tzinfo=UTC)

#: The book's own fixed equity, as the synthetic fixture spells it.
BOOK_EQUITY = "10000"

#: The account's equity off Addendum 14's read-only balance call: the live
#: figure that is *below* the book's own, so the floor picks it.
LIVE_EQUITY = "9688.8247"

#: The exact answer the rule gives for those two figures at the default
#: utilisation — ``min(10000, 9688.8247) × 0.90``, the addendum's own
#: worked example, as the exact Decimal's string.
SIZED_BELOW_BOOK = "8719.94223"


def _funded_balance(equity: str) -> dict:
    """The recorded balance row, at a re-spelled equity and a funded margin.

    Derived from ``live/balance.json`` — the venue's one row with two
    fields re-spelled, never an invented response shape, the same
    derivation the neighbouring suite makes — so the guard reads the day's
    equity out of the venue's own document while the preflight's margin
    door stays comfortably funded.
    """
    fixture = (
        Path(__file__).resolve().parent / "fixtures" / "bingx_vst" / "live"
    )
    data = json.loads((fixture / "balance.json").read_text(encoding="utf-8"))["data"]
    data["balance"]["equity"] = equity
    data["balance"]["availableMargin"] = "100000"
    return data


def _client(equity: str = LIVE_EQUITY) -> _MirrorClient:
    return _MirrorClient(balance=_funded_balance(equity))


def _write_book(tmp_path: Path, **changes) -> Path:
    """The synthetic book on disk, with overrides applied."""
    book = _book()
    book["equity_usdt"] = BOOK_EQUITY
    book.update(changes)
    path = tmp_path / "book.json"
    path.write_text(json.dumps(book), encoding="utf-8")
    return path


def _run(
    book_path: Path,
    *,
    client: _MirrorClient,
    url: str,
    env: dict | None = None,
    now: datetime = MID_SLOT,
) -> tuple[int, list[dict]]:
    """One slot of the command, as ``(exit_code, json_lines)``."""
    emitted: list[str] = []
    code = main(
        ["--book", str(book_path)],
        client=client,
        transport=None,
        store=RouterOrderPlacementStore(url),
        limiter=_CountingLimiter(),
        env={} if env is None else env,
        database_url=url,
        now=lambda: now,
        clock=_clock,
        sleep=lambda _d: None,
        alert=None,
        emit=emitted.append,
    )
    return code, [json.loads(line) for line in emitted]


class _Capturing:
    """A monkeypatch target that records the ``book`` each step is handed.

    Wraps :func:`router.bingx_mirror.build_mirror_plan` and its
    ``mirror_place`` — recording the operand and delegating to the real
    function, so the slot still walks the plan it always walks and the
    assertion is on *which equity reaches the sizer* rather than on a
    plan's arithmetic, which is where the defect lives.
    """

    def __init__(self, real_build, real_place) -> None:
        self._real_build = real_build
        self._real_place = real_place
        self.books: list[dict] = []

    def build(self, *, book, client):
        self.books.append(book)
        return self._real_build(book=book, client=client)

    def place(self, *, book, **rest):
        self.books.append(book)
        return self._real_place(book=book, **rest)


@pytest.fixture
def captured(monkeypatch: pytest.MonkeyPatch) -> _Capturing:
    """The slot's two placement steps, recorded and delegated."""
    import router.bingx_rebalance as module

    captor = _Capturing(build_mirror_plan, mirror_place)
    monkeypatch.setattr(module, "build_mirror_plan", captor.build)
    monkeypatch.setattr(module, "mirror_place", captor.place)
    return captor


# -- The reproduction ----------------------------------------------------------


def test_the_slot_sizes_from_the_live_equity_not_the_books_fixed_figure(
    tmp_path, test_database_url, captured
) -> None:
    """The defect, and the repair, on the addendum's own arithmetic.

    Before the fix the book handed to the plan and the placement carried
    ``equity_usdt`` 10000 — the whole of a 10040 USDT pool at leverage 1,
    the mis-sizing that deferred 47 legs at 12:05 UTC on 2026-10-26.
    After it the same book carries ``min(10000, 9688.8247) × 0.90``, the
    exact Decimal's own string, and the report states the three terms.
    """
    code, lines = _run(
        _write_book(tmp_path),
        client=_client(),
        url=test_database_url,
        env={},
    )

    assert code == EXIT_OK
    assert captured.books, "the slot never reached the plan or the placement"
    for book in captured.books:
        assert book["equity_usdt"] == SIZED_BELOW_BOOK
    assert lines[0]["book_equity_usdt"] == BOOK_EQUITY
    assert lines[0]["sized_equity_usdt"] == SIZED_BELOW_BOOK
    assert lines[0]["margin_utilisation"] == DEFAULT_MARGIN_UTILISATION


def test_the_old_behaviour_would_have_been_the_books_own_figure(
    tmp_path, test_database_url, captured
) -> None:
    """The floor picked the live figure: at a live equity *above* the book's
    the sized value is the book's own × the utilisation, never the live one.

    This is the other half of the rule and the reason it is a ``min``: the
    weights are fractions of the *book's* equity, so a better-funded
    account must not trade a larger book than the one registered.
    """
    code, lines = _run(
        _write_book(tmp_path),
        client=_client(equity="12000"),
        url=test_database_url,
        env={},
    )

    assert code == EXIT_OK
    # 10000 × 0.90, in the exact Decimal's own spelling: no trailing zero
    # the product's 6-place scale would otherwise carry.
    assert captured.books[0]["equity_usdt"] == "9000"
    assert lines[0]["book_equity_usdt"] == BOOK_EQUITY
    assert lines[0]["sized_equity_usdt"] == "9000"


# -- The utilisation lever ------------------------------------------------------


def test_a_utilisation_of_one_sizes_unscaled_from_the_floor(
    tmp_path, test_database_url, captured
) -> None:
    """``BINGX_VST_MARGIN_UTILISATION=1`` leaves the floor untouched."""
    code, lines = _run(
        _write_book(tmp_path),
        client=_client(),
        url=test_database_url,
        env={MARGIN_UTILISATION_ENV: "1"},
    )

    assert code == EXIT_OK
    assert captured.books[0]["equity_usdt"] == LIVE_EQUITY
    assert lines[0]["sized_equity_usdt"] == LIVE_EQUITY
    assert lines[0]["margin_utilisation"] == "1"


def test_a_custom_utilisation_scales_the_floor(
    tmp_path, test_database_url, captured
) -> None:
    """A named fraction is applied to the floor, in exact decimal."""
    code, lines = _run(
        _write_book(tmp_path),
        client=_client(),
        url=test_database_url,
        env={MARGIN_UTILISATION_ENV: "0.5"},
    )

    assert code == EXIT_OK
    assert lines[0]["sized_equity_usdt"] == str(Decimal(LIVE_EQUITY) * Decimal("0.5"))


@pytest.mark.parametrize("value", ["0", "1.5", "-0.5", "abc", "NaN", "Infinity"])
def test_a_malformed_utilisation_is_refused_before_anything_is_asked(
    tmp_path, test_database_url, captured, capsys, value
) -> None:
    """Every value outside ``(0, 1]`` is refused by name, with nothing sent.

    The refusal names the variable *and* the value, wears the module's own
    prefix, and takes the module's own malformed-input exit — and the plan
    is never built and the venue never asked, which the captured operands
    and the client's own call list both state.
    """
    client = _client()
    code, lines = _run(
        _write_book(tmp_path),
        client=client,
        url=test_database_url,
        env={MARGIN_UTILISATION_ENV: value},
    )

    assert code == EXIT_REFUSED
    assert lines == []
    assert captured.books == []
    assert client.calls == []
    error = capsys.readouterr().err
    assert error.startswith(f"{BINGX_REBALANCE_CODE}: ")
    assert MARGIN_UTILISATION_ENV in error
    assert repr(value) in error
    # The record is the module's other malformed-input refusals' own: the
    # refusal is raised out of the slot before any step runs, so no slot
    # completion is appended for a run that never started.
    assert RouterSlotCompletionStore(test_database_url).newest() is None


def test_the_book_equity_is_reported_as_the_book_spelled_it(
    tmp_path, test_database_url, captured
) -> None:
    """``book_equity_usdt`` is the book's own spelling, not a re-rendering.

    The spec's own example spells the book's equity ``"10000.0"``.  The
    report must carry that string back — the informational field exists to
    say what the *book* claimed, beside the figure the slot sized from —
    so a decimal re-rendered into another spelling would hide the very
    comparison the three fields are there to expose.
    """
    code, lines = _run(
        _write_book(tmp_path, equity_usdt="10000.0"),
        client=_client(),
        url=test_database_url,
        env={},
    )

    assert code == EXIT_OK
    assert lines[0]["book_equity_usdt"] == "10000.0"
    assert lines[0]["sized_equity_usdt"] == SIZED_BELOW_BOOK
    assert captured.books[0]["equity_usdt"] == SIZED_BELOW_BOOK


def test_the_book_equity_is_read_from_the_document_not_the_slot_book(
    tmp_path, test_database_url, captured
) -> None:
    """Only the *sizing* equity is the slot's: the book's own term is unaltered.

    A second run of the same book in a later slot — when the first slot's
    sized book is nowhere on disk — must report the book's own figure
    again, never a sized one carried over.  The document is re-read each
    run, so this pins that the stamp is the copy's and never the file's.
    """
    path = _write_book(tmp_path, equity_usdt="10000.0")
    _run(path, client=_client(), url=test_database_url, env={})
    code, lines = _run(path, client=_client(), url=test_database_url, env={})

    assert code == EXIT_OK
    assert lines[0]["book_equity_usdt"] == "10000.0"
    assert json.loads(path.read_text(encoding="utf-8"))["equity_usdt"] == "10000.0"


def test_an_empty_utilisation_falls_back_to_the_default(
    tmp_path, test_database_url, captured
) -> None:
    """An unset-or-empty variable is the default, never a refusal."""
    code, lines = _run(
        _write_book(tmp_path),
        client=_client(),
        url=test_database_url,
        env={MARGIN_UTILISATION_ENV: ""},
    )

    assert code == EXIT_OK
    assert lines[0]["margin_utilisation"] == DEFAULT_MARGIN_UTILISATION
    assert lines[0]["sized_equity_usdt"] == SIZED_BELOW_BOOK


# -- One figure everywhere ------------------------------------------------------


def test_the_plan_and_the_placement_are_handed_one_and_the_same_book(
    tmp_path, test_database_url, captured
) -> None:
    """The sizer and the fidelity recompute must read one equity.

    :func:`router.bingx_mirror.build_mirror_plan` sizes the plan and
    :func:`router.bingx_mirror.mirror_place` recomputes targets for its
    fidelity rows, both off ``book["equity_usdt"]``.  A slot that stamped
    one and not the other would record fidelity against a book nobody
    traded, so the two operands are asserted identical here — and identical
    to the figure the report states.
    """
    code, lines = _run(
        _write_book(tmp_path),
        client=_client(),
        url=test_database_url,
        env={},
    )

    assert code == EXIT_OK
    assert len(captured.books) == 2
    planned, placed = captured.books
    assert planned is placed
    assert planned["equity_usdt"] == lines[0]["sized_equity_usdt"]


def test_the_book_file_on_disk_is_byte_identical_after_the_slot(
    tmp_path, test_database_url, captured
) -> None:
    """The stamp is the slot's own copy: the operator's file never moves."""
    path = _write_book(tmp_path)
    before = path.read_bytes()

    _run(path, client=_client(), url=test_database_url, env={})

    assert path.read_bytes() == before
    assert json.loads(before)["equity_usdt"] == BOOK_EQUITY


def test_the_persisted_record_carries_the_books_own_weights(
    tmp_path, test_database_url, captured
) -> None:
    """The record keeps the construction: only the equity is the slot's.

    The rebalance's target weights are the *book's* — the sizing equity is
    an execution-side figure and must not leak into the record the book
    member keeps.
    """
    from book import RebalanceTargetWeightsStore

    book_store = RebalanceTargetWeightsStore(test_database_url)
    code, lines = _run(
        _write_book(tmp_path, originating_signal_ids=["signal-a"]),
        client=_client(),
        url=test_database_url,
        env={},
    )

    assert code == EXIT_OK
    assert lines[0]["persisted"] is True
    record = book_store.get(book_id="synthetic-vst-0", rebalance_ts=SLOT_NOON)
    assert record is not None
    assert dict(record.weights) == _book()["weights"]


def test_every_leg_is_placed_once_under_the_sized_book(
    tmp_path, test_database_url
) -> None:
    """The sized slot still places the plan it always did, once per leg.

    The capture above replaces the placement; this one runs the real path,
    so the claim is that the *repair* is not a change to what a slot does
    with a plan — only to the equity it sizes it from.
    """
    client = _client()
    code, lines = _run(
        _write_book(tmp_path), client=client, url=test_database_url, env={}
    )

    assert code == EXIT_OK
    assert len(client.placed) == 5
    assert [o["outcome"] for o in lines[0]["orders"]] == [MIRROR_OUTCOME_PLACED] * 5
    assert lines[0]["sized_equity_usdt"] == SIZED_BELOW_BOOK
    # The slot's own instant is still the one the orders are named for.
    assert lines[0]["rebalance_ts"] == SLOT_NOON.isoformat()
    assert floor_to_slot(MID_SLOT) == SLOT_NOON
