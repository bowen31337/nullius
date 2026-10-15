"""The sandbox child runs feature 12's index check (check_signal_return).

A length-conforming float series whose name claims a symbol the window does
not hold would attribute its values to the wrong symbols; the child rejects
it as a ``violation`` naming that symbol. A series named after a symbol the
window holds, or a plain column name, is the conforming return as before.
"""

from __future__ import annotations

import json
import textwrap

from test_child_lazy_stdlib_imports import run_signal

_UNIVERSE = ("BTCUSDT", "ETHUSDT", "SOLUSDT")


def _source(name: str) -> str:
    return textwrap.dedent(
        f"""
        import polars as pl

        def signal(ctx, seed):
            return pl.Series({name!r}, [1.0, 2.0, 3.0])
        """
    )


def test_a_series_named_after_an_absent_symbol_is_a_violation() -> None:
    result, rc, err = run_signal(_source("DOGEUSDT"), universe=_UNIVERSE)
    assert rc == 0, err
    assert result["fail_class"] == "violation"
    assert result["scores"] is None
    problems = json.loads(result["detail"])
    assert [(p["kind"], p["symbol"]) for p in problems] == [("absent_symbol", "DOGEUSDT")]


def test_a_present_symbol_or_a_plain_name_is_conforming() -> None:
    for name in ("BTCUSDT", "score", "", "ΔBTC"):
        result, rc, err = run_signal(_source(name), universe=_UNIVERSE)
        assert rc == 0, err
        assert result["fail_class"] is None, (name, result["detail"])
