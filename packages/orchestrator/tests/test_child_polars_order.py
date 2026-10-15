"""The sandbox child pins polars' hash-based row order (PRD P3).

Polars seeds its hasher from the OS random source in every process, so
``unique``/``group_by``/``join`` without ``maintain_order`` return rows in a
different order in each sandbox process, and one node's ic_mean moved by about
0.1% between re-evaluations. Each signal here scores a symbol by the position
its key comes back at, through the real ``python -I _sandbox_child.py``
subprocess. A pinned process answers first-appearance order every time; an
unpinned one almost never does with 400 keys.
"""

from __future__ import annotations

import base64
import json
import textwrap

import pytest
from orchestrator import _sandbox_child as child
from test_child_lazy_stdlib_imports import run_signal

_UNIVERSE = ("AAA", "BBB", "CCC")

# A 400-key frame whose keys first appear in the order 0..399; the signal
# scores symbol i by where key i comes back, so the pinned answer is [0, 1, 2].
_PRELUDE = """
import polars as pl

def _frame():
    keys = [f"k{i % 400}" for i in range(4000)]
    return pl.DataFrame({"k": keys, "v": [float(i) for i in range(4000)]})

def _score(ctx, order):
    order = list(order)
    return pl.Series([float(order.index(f"k{i}")) for i in range(len(ctx.universe))])
"""

_CASES = {
    "frame_unique": 'order = _frame().unique(subset=["k"], keep="any")["k"]',
    "frame_unique_explicit_false": 'order = _frame().unique(subset=["k"], maintain_order=False)["k"]',
    "frame_group_by": 'order = _frame().group_by("k").agg(pl.col("v").mean())["k"]',
    "lazy_group_by": 'order = _frame().lazy().group_by("k").agg(pl.len()).collect()["k"]',
    "lazy_unique": 'order = _frame().lazy().unique(subset=["k"]).collect()["k"]',
    "series_unique": 'order = _frame()["k"].unique()',
    "expr_unique": 'order = _frame().select(pl.col("k").unique())["k"]',
    "frame_join": (
        'f = _frame().unique(subset=["k"], keep="first")\n'
        '    order = f.join(f.rename({"v": "w"}), on="k")["k"]'
    ),
}


@pytest.mark.parametrize("case", sorted(_CASES))
def test_hash_ordered_operations_return_first_appearance_order(case: str) -> None:
    source = textwrap.dedent(_PRELUDE) + textwrap.dedent(
        f"""
def signal(ctx, seed):
    {_CASES[case]}
    return _score(ctx, order.to_list())
"""
    )
    for _ in range(2):
        result, rc, err = run_signal(source, universe=_UNIVERSE)
        assert rc == 0, err
        assert result["fail_class"] is None, result["detail"]
        scores = json.loads(base64.b64decode(result["scores"]).decode("utf-8"))
        assert scores == [0.0, 1.0, 2.0]


def test_pinned_wrapper_exposes_none_of_the_bootstrap_globals() -> None:
    # polars' own functions already carry ``os`` in their globals (the OS
    # sandbox is the boundary, not this); this pins that the wrapper adds no
    # route of its own to the bootstrap's module namespace.
    source = textwrap.dedent(
        """
        import polars as pl

        def signal(ctx, seed):
            leaked = "os" in pl.DataFrame.unique.__globals__
            return pl.Series([1.0 if leaked else 0.0 for _ in ctx.universe])
        """
    )
    result, rc, err = run_signal(source, universe=("AAA", "BBB"))
    assert rc == 0, err
    assert result["fail_class"] is None, result["detail"]
    scores = json.loads(base64.b64decode(result["scores"]).decode("utf-8"))
    assert scores == [0.0, 0.0]


def test_every_pinned_method_exists_on_this_polars() -> None:
    import polars

    for owner_name, method_name, _value in child._POLARS_ORDER_PINS:
        assert callable(getattr(getattr(polars, owner_name), method_name, None)), (
            owner_name,
            method_name,
        )
