"""Tests for :mod:`router.bingx_dry_run` — the plan, printed, sending nothing.

Feature 4 of additions_spec_bingx_dry_run.xml, second half: *It prints a
dry-run plan from* ``python -m router.bingx_dry_run --book BOOK
--contracts CONTRACTS --marks MARKS``, *writing one JSON object per
would-send order and one per refused leg to stdout, and exiting 0 while
sending nothing.  For the recorded fixtures and the synthetic book it
returns five orders … a below_min_notional refusal for AGLD-USDT and a
not_tradable refusal for NCFXUSD2ARS-USDT.  Every clientOrderID it
prints is at most 40 characters and equals feature 3's projection, and
with socket creation patched to raise the command still exits 0, proving
no connection is opened and no environment variable or credential is
read.*  These tests hold the command to every clause of that sentence
over the recorded fixtures — including the socket-patched, empty-environment
subprocess proof, which is the sentence's own test of the module's law.

The fixtures under ``fixtures/bingx_vst/`` are inputs and are never edited
here; the mutated documents these tests build are copies, in tmp paths or
in memory.  The weights reach the sizer through feature 305's own seam —
never a bare dict — and one test spies on that seam to prove the plan
publishes through it.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import pytest
from router.bingx_client_order_id import project_bingx_client_order_id
from router.bingx_documents import MARK_PRICE_CODE, NOT_TRADABLE_CODE
from router.bingx_dry_run import (
    BINGX_DRY_RUN_CODE,
    RouterBingXDryRunError,
    dry_run_plan,
    main,
)
from router.bingx_order import BingXRefusedLeg
from router.client_order_id import derive_client_order_id
from router.errors import BELOW_MIN_NOTIONAL_CODE

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "bingx_vst"

# conftest -> packages/router/tests -> packages/router -> packages -> repo root
REPO_ROOT = Path(__file__).resolve().parents[3]

#: The workspace roots the command's own imports resolve through, in the
#: order the member conftest puts them on ``sys.path`` — the same set,
#: spelled absolutely, so the subprocess tests run the real ``python -m``
#: command rather than an in-process imitation of it.
COMMAND_ROOTS = (
    REPO_ROOT / "src",
    REPO_ROOT / "packages" / "router" / "src",
    REPO_ROOT / "packages" / "book" / "src",
    REPO_ROOT / "packages" / "ingest" / "src",
)

#: The six symbols the venue's own documents make tradeable — status 1
#: and priced.  NCFXUSD2ARS-USDT is held by the book but status 25 and
#: unpriced; AGLD-USDT is tradeable and priced and is refused later, by a
#: gate, so both refusals are visible in one plan.
TRADABLE = {
    "BTC-USDT",
    "ETH-USDT",
    "SOL-USDT",
    "DOGE-USDT",
    "1000PEPE-USDT",
    "AGLD-USDT",
}


def _fixture(name: str) -> dict:
    """One recorded VST fixture, decoded verbatim from disk."""
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _plan(book: object = None) -> list:
    """The plan over the recorded fixtures, or over ``book`` when handed one."""
    return dry_run_plan(
        book=book if book is not None else _fixture("synthetic_book.json"),
        contracts=_fixture("contracts.json"),
        marks=_fixture("premium_index.json"),
    )


def _projected_id(symbol: str) -> str:
    """Feature 3's projection of feature 316's identifier for one leg."""
    book = _fixture("synthetic_book.json")
    return project_bingx_client_order_id(
        derive_client_order_id(
            book_id=book["book_id"],
            rebalance_ts=datetime.fromisoformat(book["rebalance_ts"]),
            symbol=symbol,
        )
    )


def _expected_orders() -> list[dict[str, str]]:
    """The spec's five would-send orders, as parameter objects.

    Exactly the sentence's own pinned values, in the sorted symbol order
    the plan answers in — BTC-USDT's trailing zero, 1000PEPE-USDT's
    seven-decimal price, DOGE-USDT's price-less MARKET object — with the
    clientOrderIDs read through feature 3's projection at runtime,
    because *equals feature 3's projection* is the assertion, not the
    value of the hash.
    """
    return [
        {
            "symbol": "1000PEPE-USDT",
            "side": "BUY",
            "positionSide": "BOTH",
            "type": "LIMIT",
            "quantity": "69446",
            "price": "0.0043199",
            "timeInForce": "PostOnly",
            "clientOrderID": _projected_id("1000PEPE-USDT"),
        },
        {
            "symbol": "BTC-USDT",
            "side": "BUY",
            "positionSide": "BOTH",
            "type": "LIMIT",
            "quantity": "0.0140",
            "price": "83137.3",
            "timeInForce": "PostOnly",
            "clientOrderID": _projected_id("BTC-USDT"),
        },
        {
            "symbol": "DOGE-USDT",
            "side": "SELL",
            "positionSide": "BOTH",
            "type": "MARKET",
            "quantity": "5329",
            "clientOrderID": _projected_id("DOGE-USDT"),
        },
        {
            "symbol": "ETH-USDT",
            "side": "SELL",
            "positionSide": "BOTH",
            "type": "LIMIT",
            "quantity": "0.558",
            "price": "2685.87",
            "timeInForce": "PostOnly",
            "clientOrderID": _projected_id("ETH-USDT"),
        },
        {
            "symbol": "SOL-USDT",
            "side": "BUY",
            "positionSide": "BOTH",
            "type": "LIMIT",
            "quantity": "8.44",
            "price": "118.392",
            "timeInForce": "PostOnly",
            "clientOrderID": _projected_id("SOL-USDT"),
        },
    ]


#: The spec's two refused legs, in the same sorted order.
EXPECTED_REFUSALS = [
    ("AGLD-USDT", BELOW_MIN_NOTIONAL_CODE),
    ("NCFXUSD2ARS-USDT", NOT_TRADABLE_CODE),
]


def _run_command(extra_path: Path | None = None) -> subprocess.CompletedProcess:
    """Run the real command, in a subprocess, under a minimal environment.

    ``python -m router.bingx_dry_run`` over the recorded fixture paths,
    with ``PATH`` and ``PYTHONPATH`` and nothing else — no inherited
    environment at all, so a test that passes is also a test that no
    environment variable was read on the way.  ``extra_path`` is put
    first on ``PYTHONPATH`` for the socket-patched proof, whose
    ``sitecustomize`` must load before anything else.
    """
    roots = ([str(extra_path)] if extra_path is not None else []) + [
        str(root) for root in COMMAND_ROOTS
    ]
    environment = {
        "PATH": os.environ.get("PATH", ""),
        "PYTHONPATH": os.pathsep.join(roots),
    }
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "router.bingx_dry_run",
            "--book",
            str(FIXTURES / "synthetic_book.json"),
            "--contracts",
            str(FIXTURES / "contracts.json"),
            "--marks",
            str(FIXTURES / "premium_index.json"),
        ],
        capture_output=True,
        text=True,
        env=environment,
        cwd=str(REPO_ROOT),
        timeout=120,
        check=False,
    )


def test_the_recorded_fixtures_answer_five_orders_and_two_refusals() -> None:
    """The spec's own seven legs, exactly, in the book's sorted symbol order.

    Five orders — the two clauses of the assembly sentence over the six
    sizeable symbols — and two refusals that are *answers of the same
    act*: AGLD-USDT closed by the notional floor (a gate's code word),
    NCFXUSD2ARS-USDT closed by the contracts document itself (feature 1's
    own ``not_tradable``).  And deterministic: the same three documents
    answer the same plan twice, so two operators running the command read
    byte-identical output.
    """
    plan = _plan()
    orders = [leg for leg in plan if not isinstance(leg, BingXRefusedLeg)]
    refusals = [leg for leg in plan if isinstance(leg, BingXRefusedLeg)]

    assert [order.parameters() for order in orders] == _expected_orders()
    assert [(leg.symbol, leg.code) for leg in refusals] == EXPECTED_REFUSALS
    # Sorted symbol order, both kinds side by side: 1000PEPE, AGLD, BTC,
    # DOGE, ETH, NCFXUSD2ARS, SOL.
    assert [leg.symbol for leg in plan] == [
        "1000PEPE-USDT",
        "AGLD-USDT",
        "BTC-USDT",
        "DOGE-USDT",
        "ETH-USDT",
        "NCFXUSD2ARS-USDT",
        "SOL-USDT",
    ]
    # BingX's hyphenated spelling end to end — nothing maps to BTCUSDT.
    for leg in plan:
        assert "BTCUSDT" not in leg.symbol
        assert leg.symbol.endswith("-USDT")
    # Deterministic: the same documents, the same plan, again.
    assert _plan() == plan


def test_every_printed_client_order_id_is_at_most_40_characters() -> None:
    """Every id on the plan is feature 3's 40-character projection.

    The venue's field caps the system's 64-hex identifier at 40, and the
    projection is applied once at the boundary — so the plan carries no
    full identifier anywhere, and nothing downstream joins on the short
    form (the placement store's key stays the full 64 hex, elsewhere).
    """
    for order in [leg for leg in _plan() if not isinstance(leg, BingXRefusedLeg)]:
        identifier = order.parameters()["clientOrderID"]
        assert len(identifier) <= 40
        assert identifier == _projected_id(order.symbol)


def test_the_command_prints_one_json_object_per_leg_and_exits_zero() -> None:
    """``python -m router.bingx_dry_run`` answers the spec's plan on stdout.

    One JSON object per leg, one per line, in the plan's own order — and
    the objects are exactly the in-process plan's values, so the command
    adds and changes nothing on the way out.  Exit 0: the two refused
    legs are answers the plan states, not failures of the command.
    """
    completed = _run_command()
    assert completed.returncode == 0, completed.stderr

    lines = completed.stdout.splitlines()
    assert len(lines) == 7
    for line, leg in zip(lines, _plan()):
        if isinstance(leg, BingXRefusedLeg):
            assert json.loads(line) == {"symbol": leg.symbol, "refusal": leg.code}
        else:
            assert json.loads(line) == leg.parameters()

    printed = [json.loads(line) for line in lines]
    assert [obj for obj in printed if "side" in obj] == _expected_orders()
    assert [
        (obj["symbol"], obj["refusal"]) for obj in printed if "refusal" in obj
    ] == EXPECTED_REFUSALS


def test_the_command_exits_zero_with_socket_creation_patched_to_raise(
    tmp_path: Path,
) -> None:
    """The sentence's own proof: sockets refused, environment empty, exit 0.

    A ``sitecustomize`` on ``PYTHONPATH`` replaces ``socket.socket``,
    ``create_connection``, ``getaddrinfo`` and ``socketpair`` with
    functions that raise, so any connection any import path tried to open
    would crash the command.  The environment carries ``PATH`` and
    ``PYTHONPATH`` and nothing else — no ``DATABASE_URL`` for a store to
    address, no credentials, no keys — and the command still prints all
    seven legs and exits 0: nothing is opened, nothing is read, nothing
    is persisted.
    """
    site_dir = tmp_path / "socket-patch"
    site_dir.mkdir()
    (site_dir / "sitecustomize.py").write_text(
        "def _refused(*args, **kwargs):\n"
        "    raise AssertionError('socket creation refused')\n"
        "\n"
        "import socket\n"
        "socket.socket = _refused\n"
        "socket.create_connection = _refused\n"
        "socket.getaddrinfo = _refused\n"
        "socket.socketpair = _refused\n",
        encoding="utf-8",
    )
    completed = _run_command(extra_path=site_dir)
    assert completed.returncode == 0, completed.stderr
    assert len(completed.stdout.splitlines()) == 7


def test_the_socket_patch_bites_the_command_not_just_this_test(
    tmp_path: Path,
) -> None:
    """A control for the proof: the patch mechanism itself must bite.

    The socket-patched proof is silence, and silence only means anything
    if the patch is really loaded and really applies.  So the same
    mechanism patches ``json.dumps`` instead — which the command cannot
    help calling, one object per leg — and the command must fail, proving
    the ``sitecustomize`` on ``PYTHONPATH`` runs first and its patches
    take effect.  With that shown, the socket-patched run's exit 0 is a
    measurement, not a vacuous pass.
    """
    site_dir = tmp_path / "control-patch"
    site_dir.mkdir()
    (site_dir / "sitecustomize.py").write_text(
        "def _refused(*args, **kwargs):\n"
        "    raise AssertionError('json.dumps refused')\n"
        "\n"
        "import json\n"
        "json.dumps = _refused\n",
        encoding="utf-8",
    )
    completed = _run_command(extra_path=site_dir)
    assert completed.returncode != 0
    assert "json.dumps refused" in completed.stderr


def test_the_book_is_published_through_feature_305s_seam(monkeypatch) -> None:
    """The weights reach the sizer as a published record, never a bare dict.

    The spec's integration points are explicit: the dry run *"publishes
    it through the book member's own book.final_target_weights so the
    weights arrive through feature 305's seam rather than as a bare
    dict"*.  Spying on that seam shows one publication, over the six
    symbols the venue's documents make tradeable — the not_tradable leg
    was recorded before publication and never reaches the weights —
    carrying the book's own float weights.
    """
    import book

    calls: list[object] = []
    original = book.final_target_weights

    def _spy(record: object) -> object:
        calls.append(record)
        return original(record)

    monkeypatch.setattr(book, "final_target_weights", _spy)
    _plan()

    assert len(calls) == 1
    published = calls[0].weights
    assert set(published) == TRADABLE
    book_weights = _fixture("synthetic_book.json")["weights"]
    assert published == {symbol: book_weights[symbol] for symbol in TRADABLE}


def test_a_leg_already_at_its_target_prints_no_line() -> None:
    """A zero delta produces no order, so no line carries one.

    BTC-USDT held at exactly its truncated target (0.0240 against the
    recorded mark and grid) sizes to zero and answers no leg at all —
    the absence of a key, never a zero quantity an order would carry —
    and the rest of the plan stands unchanged.
    """
    book = _fixture("synthetic_book.json")
    book["positions"] = {"BTC-USDT": "0.0240"}
    plan = _plan(book)
    assert [leg.symbol for leg in plan] == [
        "1000PEPE-USDT",
        "AGLD-USDT",
        "DOGE-USDT",
        "ETH-USDT",
        "NCFXUSD2ARS-USDT",
        "SOL-USDT",
    ]


def test_a_tradable_leg_with_no_mark_is_refused_missing_mark_price() -> None:
    """One row deleted from the premiumIndex changes one leg's refusal.

    The same book and contracts with AGLD-USDT's mark row removed: the
    leg is tradeable, so it reaches the marks read and is refused there
    by feature 1's own code word — ``missing_mark_price`` instead of the
    ``below_min_notional`` the priced document answers.  The plan still
    carries seven legs; only the reason one leg would not send changed.
    """
    marks = _fixture("premium_index.json")
    marks["data"] = [
        row for row in marks["data"] if row["symbol"] != "AGLD-USDT"
    ]
    plan = dry_run_plan(
        book=_fixture("synthetic_book.json"),
        contracts=_fixture("contracts.json"),
        marks=marks,
    )
    refusals = [
        (leg.symbol, leg.code)
        for leg in plan
        if isinstance(leg, BingXRefusedLeg)
    ]
    assert refusals == [
        ("AGLD-USDT", MARK_PRICE_CODE),
        ("NCFXUSD2ARS-USDT", NOT_TRADABLE_CODE),
    ]
    assert MARK_PRICE_CODE == "missing_mark_price"


def test_a_held_symbol_the_contracts_document_never_named_is_refused() -> None:
    """A book and a document that disagree about what exists is a fault of the ask.

    Not a leg the venue closed — that is ``not_tradable``, a contract
    listed and closed — but a weight the venue's own document never
    lists at all.  A silently dropped weight would be indistinguishable
    from a weight the book never held, so the plan refuses naming the
    symbol rather than sizing six of seven legs.
    """
    book = _fixture("synthetic_book.json")
    book["weights"]["ZZZ-USDT"] = 0.05
    book["decay_horizon_seconds"]["ZZZ-USDT"] = 14400
    with pytest.raises(RouterBingXDryRunError) as raised:
        _plan(book)
    message = str(raised.value)
    assert message.startswith(f"{BINGX_DRY_RUN_CODE}: ")
    assert "ZZZ-USDT" in message


@pytest.mark.parametrize(
    "case",
    [
        pytest.param("not_a_mapping", id="not-a-mapping"),
        pytest.param("no_weights", id="no-weights"),
        pytest.param("empty_weights", id="empty-weights"),
        pytest.param("blank_symbol", id="blank-symbol"),
        pytest.param("no_equity", id="no-equity"),
        pytest.param("no_decay", id="no-decay"),
        pytest.param("naive_ts", id="naive-rebalance-ts"),
        pytest.param("unparsable_ts", id="unparsable-rebalance-ts"),
        pytest.param("no_book_id", id="no-book-id"),
    ],
)
def test_a_book_that_is_not_the_stage_0_shape_is_refused(case: str) -> None:
    """The ask's own faults refuse before any leg is assembled.

    Each mutation breaks one term of the book's own shape, and each is
    refused with this command's code word — on stderr in the command,
    never folded into a leg on stdout — because a plan that unwound
    halfway through printing would be a plan nobody could read twice.
    The equity, the positions and the margin mode are deliberately *not*
    judged here: their refusals are feature 2's and feature 315's own
    vocabularies, and this command hands them through verbatim.
    """
    book = _fixture("synthetic_book.json")
    if case == "not_a_mapping":
        document: object = ["not", "a", "book"]
        expected = "is a JSON object"
    else:
        if case == "no_weights":
            del book["weights"]
            expected = "no weights"
        elif case == "empty_weights":
            book["weights"] = {}
            expected = "no weights"
        elif case == "blank_symbol":
            book["weights"]["   "] = 0.1
            expected = "non-empty symbol names"
        elif case == "no_equity":
            del book["equity_usdt"]
            expected = "no equity_usdt"
        elif case == "no_decay":
            del book["decay_horizon_seconds"]["SOL-USDT"]
            expected = "decay horizon"
        elif case == "naive_ts":
            book["rebalance_ts"] = "2026-09-30T00:00:00"
            expected = "names no timezone"
        elif case == "unparsable_ts":
            book["rebalance_ts"] = "not-an-instant"
            expected = "not an ISO 8601 instant"
        else:
            assert case == "no_book_id"
            del book["book_id"]
            expected = "book_id"
        document = book

    with pytest.raises(RouterBingXDryRunError) as raised:
        dry_run_plan(
            book=document,
            contracts=_fixture("contracts.json"),
            marks=_fixture("premium_index.json"),
        )
    message = str(raised.value)
    assert message.startswith(f"{BINGX_DRY_RUN_CODE}: ")
    assert expected in message


def test_a_path_that_will_not_read_exits_one_on_stderr(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    """Exit 1 and the code word on stderr are reserved for faults of the ask.

    A missing path and a document that is not JSON are repairs to make
    before any plan is worth reading; stdout stays empty so nothing
    half-printed can be mistaken for a plan.
    """
    absent = main(
        [
            "--book",
            str(tmp_path / "absent.json"),
            "--contracts",
            str(FIXTURES / "contracts.json"),
            "--marks",
            str(FIXTURES / "premium_index.json"),
        ]
    )
    assert absent == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.startswith("bingx_dry_run: ")

    (tmp_path / "book.json").write_text("not json", encoding="utf-8")
    unparsable = main(
        [
            "--book",
            str(tmp_path / "book.json"),
            "--contracts",
            str(FIXTURES / "contracts.json"),
            "--marks",
            str(FIXTURES / "premium_index.json"),
        ]
    )
    assert unparsable == 1
    assert "is not JSON" in capsys.readouterr().err


def test_the_command_requires_its_three_paths() -> None:
    """``--book``, ``--contracts`` and ``--marks`` are the command's whole interface."""
    with pytest.raises(SystemExit) as raised:
        main([])
    assert raised.value.code == 2
