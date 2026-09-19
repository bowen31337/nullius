"""Feature 73 — executing a signal inside the sandbox.

app_spec.xml feature 73: *"System executes the signal function inside the
sandbox, which returns a raw score vector per rebalance date."*
docs/nullius-tech-architecture.md §6.1 names the step —
``2. execute_signal (sandbox) → raw score vector per rebalance date`` — and
§5.2 shows the call it makes::

    result = sandbox.run(entrypoint="signal", code=node.code,
                         payload=window.to_arrow(), limits=…, seed=node.seed)

This suite tests each claim in that call separately, because a sandbox that
satisfied any two of them would be a different and worse feature:

* **runs the signal** — a conforming signal returns a :class:`SandboxResult`
  with :attr:`~SandboxResult.scores` set and no :attr:`~SandboxResult.fail_class`;
* **inside the sandbox** — the signal runs in a child process, never the host,
  so a signal that raises, loops forever, or exhausts memory is recorded as a
  value (:class:`SandboxResult`), not raised to the caller;
* **under hard limits** — the wall/CPU budget fires ``timeout``, the address
  space fires ``oom``;
* **returns a raw score vector** — the values come back positional against the
  window's universe, validated against the signal contract (feature 11/12);
* **determinism** — the child runs under §12's single-threaded-BLAS and fixed
  hash-seed pins, which the sandbox *guarantees* rather than hoping for.

Every signal below is handed a real :class:`~contract.window.MarketWindow`
over a real Arrow frame, serialized over the payload channel and reconstructed
in the child — the same boundary the host crosses — so the sandbox is tested
against the actual payload handle, not a hand-written stand-in.  A failed run
is a value, never an exception (see :class:`SandboxResult`), so the resource
and contract failures are asserted on the returned object rather than with
``pytest.raises``.
"""

from __future__ import annotations

import os
import sys

import pyarrow as pa
import pytest
from contract import MarketWindow

from evaluator import (
    EvaluatorSandboxError,
    SandboxLimits,
    SandboxResult,
    SignalSandbox,
)

_SRC = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))


def _window(universe=("AAA", "BBB", "CCC")) -> MarketWindow:
    """A one-frame window with a row per symbol, ready to serialize."""
    frames = {
        "bars:1d": pa.table(
            {"symbol": list(universe), "open_time": list(range(1, len(universe) + 1))}
        )
    }
    return MarketWindow("2026-09-01T00:00:00Z", universe=tuple(universe), frames=frames)


def _run(code: str, window: MarketWindow | None = None, *, seed: int = 1,
         limits: SandboxLimits | None = None) -> SandboxResult:
    return SignalSandbox().run(
        code, window if window is not None else _window(), seed=seed, limits=limits
    )


# -- runs the signal ---------------------------------------------------------


def test_a_conforming_signal_returns_scores_and_no_fail_class() -> None:
    # The signal's whole contract: return a Series, one value per universe
    # symbol.  A conforming return is a result with scores, no fail_class, and
    # the values positional against the window's universe.
    result = _run(
        "def signal(ctx, seed):\n    return pl.Series([1.0, -2.0, 0.5])"
    )
    assert result.fail_class is None
    assert result.ok
    assert result.scores is not None
    assert result.scores.to_list() == [1.0, -2.0, 0.5]
    assert result.problems == []
    # The contract version the execution ran under is carried back (§15's ABI).
    assert result.contract_version


def test_scores_are_positional_against_the_universe() -> None:
    # The i-th value is the score for the i-th symbol of the universe (feature
    # 11: the window carries the labels, the series carries the values).  The
    # sandbox ships the values; the window's order is the alignment.
    result = _run("def signal(ctx, seed):\n    return pl.Series([9.0, 8.0, 7.0])")
    assert result.scores.to_list() == [9.0, 8.0, 7.0]


def test_a_seed_is_carried_back_on_the_result() -> None:
    # The seed the signal ran with travels on the result, so a persisted score
    # can say which source of randomness produced it.
    result = _run("def signal(ctx, seed):\n    return pl.Series([float(seed)])", seed=7)
    assert result.seed == 7


# -- the signal contract runs in the child (feature 11/12) --------------------


def test_a_wrong_length_return_is_a_violation_with_problems() -> None:
    # Two values for a three-symbol universe: the contract validator runs in
    # the child and names the problem.  A violation is not ``ok`` and carries
    # no scores, but it is *not* a resource failure — the sandbox ran to
    # completion.
    result = _run("def signal(ctx, seed):\n    return pl.Series([1.0, 2.0])")
    assert result.fail_class == "violation"
    assert result.scores is None
    assert [p.kind for p in result.problems] == ["wrong_length"]


def test_a_non_finite_value_is_a_violation() -> None:
    # A NaN in the return is a contract problem (feature 11), reported as a
    # violation rather than a crash.
    result = _run(
        "def signal(ctx, seed):\n    return pl.Series([1.0, float('nan'), 2.0])"
    )
    assert result.fail_class == "violation"
    assert [p.kind for p in result.problems] == ["non_finite_value"]


def test_a_non_series_return_is_a_violation() -> None:
    # Returning a bare list is not a Series; the validator refuses it as a
    # violation, not a crash.
    result = _run("def signal(ctx, seed):\n    return [1.0, 2.0, 3.0]")
    assert result.fail_class == "violation"
    assert result.problems


# -- resource failures are values, not exceptions -----------------------------


def test_a_signal_that_raises_is_a_crash() -> None:
    # A signal that raises is recorded as a crash — the sandbox ran, the signal
    # did not produce a score.  Never raised to the caller.
    result = _run("def signal(ctx, seed):\n    raise ValueError('boom')")
    assert result.fail_class == "crash"
    assert result.scores is None
    assert "boom" in result.detail


def test_a_cpu_bound_signal_is_a_timeout() -> None:
    # A signal that never yields exhausts its CPU budget.  The child's SIGXCPU
    # handler writes the 'timeout' envelope and exits — so a timeout is a
    # resource failure, not a signal-9 crash.  The CPU limit fires well before
    # the wall, so this is fast.
    result = _run(
        "def signal(ctx, seed):\n    while True:\n        pass",
        limits=SandboxLimits(wall_s=30, cpu_s=1),
    )
    assert result.fail_class == "timeout"
    assert result.scores is None


def test_a_wall_bound_signal_is_a_timeout() -> None:
    # A signal that spends most of its time sleeping never hits the CPU budget,
    # so only the wall-clock watchdog can catch it — and the watchdog records
    # the same 'timeout' class the CPU path does.  The wall is the outer bound.
    result = _run(
        "def signal(ctx, seed):\n    import time\n    time.sleep(20)\n    return pl.Series([1.0, 2.0, 3.0])",
        limits=SandboxLimits(wall_s=3, cpu_s=30),
    )
    assert result.fail_class == "timeout"
    assert result.scores is None


def test_an_unbounded_allocation_is_an_oom() -> None:
    # A signal that allocates past the address-space cap is an oom, not the
    # generic crash a broad except would give — RLIMIT_AS is enforced and the
    # pipeline distinguishes "ran out of memory" from "raised".
    result = _run(
        "def signal(ctx, seed):\n    return pl.Series([float(sum(bytearray(300*1024*1024)))])",
        limits=SandboxLimits(wall_s=10, mem_mb=128),
    )
    assert result.fail_class == "oom"
    assert result.scores is None


# -- determinism env (feature 12) ---------------------------------------------


def test_the_child_runs_under_the_determinism_pins() -> None:
    # §12's pins — single-threaded BLAS and a fixed hash seed — are guaranteed
    # by the sandbox, not hoped for.  A signal that reads its environment must
    # see them, so determinism is enforced rather than assumed.
    code = (
        "def signal(ctx, seed):\n"
        "    import os\n"
        "    ok = (\n"
        "        os.environ['OMP_NUM_THREADS'] == '1'\n"
        "        and os.environ['MKL_NUM_THREADS'] == '1'\n"
        "        and os.environ['PYTHONHASHSEED'] == '0'\n"
        "    )\n"
        "    return pl.Series([1.0 if ok else 0.0, 0.0, 0.0])"
    )
    result = _run(code)
    assert result.ok
    assert result.scores.to_list()[0] == 1.0


def test_the_determinism_env_is_spelled_once() -> None:
    # The pins are named in one place (evaluator._sandbox's ENV_* constants),
    # so the environment the sandbox guarantees cannot drift across call sites.
    from evaluator import _sandbox

    assert _sandbox.ENV_OMP == "OMP_NUM_THREADS"
    assert _sandbox.ENV_MKL == "MKL_NUM_THREADS"
    assert _sandbox.ENV_HASHSEED == "PYTHONHASHSEED"


# -- immutability of the window inside the sandbox ----------------------------


def test_the_window_is_immutable_inside_the_child() -> None:
    # The child's window is the real MarketWindow, whose read-only accessors
    # hold (§5/§6's invariant).  A signal that tries to mutate it must fail —
    # the sandbox hands a sealed slice, not a mutable object.
    code = (
        "def signal(ctx, seed):\n"
        "    try:\n"
        "        ctx.t = None\n"
        "        mutated = True\n"
        "    except Exception:\n"
        "        mutated = False\n"
        "    return pl.Series([0.0 if mutated else 1.0, 1.0, 1.0])"
    )
    result = _run(code)
    assert result.ok
    assert result.scores.to_list() == [1.0, 1.0, 1.0]


def test_the_signal_sees_the_resolved_universe() -> None:
    # The window the sandbox hands the signal carries the universe feature 72
    # resolved — the labels the positional scores align to.
    code = (
        "def signal(ctx, seed):\n"
        "    ok = ctx.universe == ('AAA', 'BBB', 'CCC')\n"
        "    return pl.Series([1.0 if ok else 0.0, 0.0, 0.0])"
    )
    result = _run(code)
    assert result.ok
    assert result.scores.to_list()[0] == 1.0


# -- payload-only boundary ----------------------------------------------------


def test_the_child_is_handed_no_mount_or_path() -> None:
    # The sandbox's boundary is the payload channel: the child is handed the
    # window's frames and nothing else.  The window a signal receives carries
    # no path and no mount — there is no filesystem handle to reach past the
    # data it was given.  (In this pure-Python implementation the child still
    # inherits the host's own filesystem; the *sandbox* provides no mount, and
    # a gVisor deployment enforces the namespace boundary.  What this feature
    # guarantees is that the window carries no path of its own.)
    code = (
        "def signal(ctx, seed):\n"
        "    has_path = 1.0 if hasattr(ctx, 'path') else 0.0\n"
        "    has_mount = 1.0 if hasattr(ctx, 'mount') else 0.0\n"
        "    return pl.Series([has_path + has_mount, 0.0, 0.0])"
    )
    result = _run(code)
    assert result.ok
    # Neither a path nor a mount attribute was carried on the window.
    assert result.scores.to_list() == [0.0, 0.0, 0.0]


def test_the_window_carries_only_the_named_frames() -> None:
    # The sandbox hands the signal the payload's frames — the ones the
    # resolution named — and no others.  A window materialized with no frames
    # gives the signal an empty frame surface, proving the boundary carries
    # only what was serialized, never a live mount.
    code = (
        "def signal(ctx, seed):\n"
        "    frames = getattr(ctx, 'frames', None)\n"
        "    n = 0 if frames is None else len(list(frames.keys()))\n"
        "    return pl.Series([float(n), 0.0, 0.0])"
    )
    result = _run(code, _window())
    assert result.ok
    # The one named frame ('bars:1d') is the surface the signal sees.
    assert result.scores.to_list()[0] == 1.0


# -- the runner itself can be driven ------------------------------------------


def test_a_window_without_a_payload_channel_is_refused() -> None:
    # The sandbox's boundary is the payload channel: it needs a materialized
    # window (one with ``to_arrow()``) to serialize.  A caller that hands it a
    # window that has materialized nothing is refused by name — the runner
    # cannot be driven, which is an ``EvaluatorSandboxError``, a failure of the
    # runner, not of the signal it ran.
    with pytest.raises(EvaluatorSandboxError, match="materialized MarketWindow"):
        SignalSandbox().run(
            "def signal(ctx, seed):\n    return pl.Series([1.0])", object(), seed=1
        )


def test_a_window_that_cannot_be_serialized_is_a_payload_failure() -> None:
    # A window that exposes the payload channel but whose bytes cannot be
    # shipped is a boundary failure ('payload'), not a signal crash — the
    # sandbox reports the failure of the channel, not of the code it ran.
    class _BadPayload:
        def to_arrow(self):
            class _NonBytes:
                def __bytes__(self) -> bytes:
                    raise ValueError("cannot convert to bytes")

            return _NonBytes()

    result = SignalSandbox().run(
        "def signal(ctx, seed):\n    return pl.Series([1.0])", _BadPayload(), seed=1
    )
    assert result.fail_class == "payload"
    assert result.scores is None


def test_an_invalid_limit_is_refused_at_construction() -> None:
    # A limits object validates its budgets at construction, so a negative or
    # non-numeric cap fails loudly rather than carrying a bad budget into a fork.
    with pytest.raises(EvaluatorSandboxError, match="positive"):
        SandboxLimits(cpu_s=-1)
    with pytest.raises(EvaluatorSandboxError, match="positive integer"):
        SandboxLimits(mem_mb=0)


def test_the_sandbox_is_deterministic_across_runs() -> None:
    # The same signal over the same window returns the same vector every time —
    # the determinism §12 requires, now enforced by the sandbox rather than
    # left to the deployment.
    code = "def signal(ctx, seed):\n    return pl.Series([1.0, -2.0, 0.5])"
    first = _run(code)
    second = _run(code)
    assert first.scores.to_list() == second.scores.to_list() == [1.0, -2.0, 0.5]
