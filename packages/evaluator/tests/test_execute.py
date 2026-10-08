"""Feature 73 — executing a signal over a resolved window, one vector per date.

app_spec.xml feature 73: *"System executes the signal function inside the
sandbox, which returns a raw score vector per rebalance date."*
docs/nullius-tech-architecture.md §6.1 names the step —
``2. execute_signal (sandbox) → raw score vector per rebalance date`` — and
§5.2 shows the call it makes::

    window = materialize_window(snapshot, t, lookback=L, universe=U)   # HOST side, Z0
    result = sandbox.run(entrypoint="signal", code=node.code,
                         payload=window.to_arrow(), limits=…, seed=node.seed)

This suite tests the orchestration — the *per rebalance date* half of the
feature sentence — separately from the process sandbox (which
``test_sandbox.py`` covers), because the two are independently testable and a
bug in one would be masked by the other:

* **per rebalance date** — :func:`execute_signal` over a resolution with N
  rebalance dates returns a :class:`SignalExecution` with N vectors, keyed by
  date, each sliced to that date's decision time;
* **the materialize seam** — the default materialize reads only the
  resolution's surviving partitions (no date past ``t`` is served), and an
  injected materialize is used (proving the seam is real, not hard-wired);
* **the identity terms** — ``code_hash`` is ``sha256(code)`` and stable, and
  the seed travels on every vector;
* **the contract is attached but not acted upon** — a violating return
  populates a vector's ``problems`` but does not raise (feature 12's
  consequence is a downstream feature's decision);
* **the sandbox is injectable** — a stub :class:`SignalSandbox` that returns
  canned results drives the loop, proving ``_execute`` and the process sandbox
  are decoupled.

The process sandbox is stubbed below (a :class:`StubSandbox` returns canned
:class:`SandboxResult` objects), so these tests assert the orchestration — the
map of dates to vectors, the materialize seam, the identity terms — without
spawning a process.  The one test that exercises the real sandbox does so over
a resolution with a single date, so the suite proves both halves: the loop is
correct against a stub, and it drives the real child end to end.
"""

from __future__ import annotations

import datetime as dt
import hashlib
from types import MappingProxyType

import polars as pl
import pytest
from contract import CONTRACT_VERSION, MarketWindow

from evaluator import (
    EvaluatorSignalError,
    RawScoreVector,
    SandboxResult,
    SignalExecution,
    SignalSandbox,
    WindowResolution,
    execute_signal,
)

_CONFORMING = "def signal(ctx, seed):\n    return pl.Series([1.0])"
_VIOLATING = "def signal(ctx, seed):\n    return pl.Series([1.0, 2.0])"


def _resolution(
    *,
    universe=("AAA", "BBB"),
    bars: dict[str, tuple[str, ...]] | None = None,
    snapshot_name: str = "snap_abc123",
) -> WindowResolution:
    """A hand-built resolution — feature 72's output — as the loop consumes it.

    ``slices`` is ``{stream: {symbol: (ISO dates at or before t, …)}}``; the
    bars dates are the rebalance grid the default path scores at.
    """
    return WindowResolution(
        snapshot_name=snapshot_name,
        t=dt.datetime(2026, 9, 2, tzinfo=dt.timezone.utc),
        universe=tuple(universe),
        slices=MappingProxyType(
            {"bars": MappingProxyType(bars if bars is not None else {
                "AAA": ("2026-09-01", "2026-09-02"),
                "BBB": ("2026-09-01", "2026-09-02"),
            })}
        ),
    )


class StubSandbox(SignalSandbox):
    """A sandbox that returns canned results, driving the loop without a child.

    The process sandbox and the orchestration are decoupled by the injectable
    ``sandbox`` parameter; this stub proves it.  It records the windows it was
    handed, so a test can assert the loop sliced one per rebalance date.
    """

    def __init__(self, *, fail_class: str | None = None, problems: list | None = None,
                 scores: tuple[float, ...] = (1.0,)) -> None:
        self._fail_class = fail_class
        self._problems = problems or []
        self._scores = scores
        self.windows: list[MarketWindow] = []

    def run(self, code: str, window: object, *, seed: int, limits=None) -> SandboxResult:
        self.windows.append(window)  # type: ignore[arg-type]
        scores = None if self._fail_class else pl.Series(list(self._scores))
        return SandboxResult(
            scores=scores,
            problems=list(self._problems),
            fail_class=self._fail_class,
            detail="",
            seed=seed,
            contract_version=CONTRACT_VERSION,
        )


# -- one vector per rebalance date -------------------------------------------


def test_execute_signal_returns_one_vector_per_rebalance_date() -> None:
    # The feature's whole sentence: two rebalance dates → two vectors, keyed by
    # date.  A single execution would be a different and worse feature — this
    # is a map of dates to vectors.
    sandbox = StubSandbox()
    execution = execute_signal(_resolution(), _CONFORMING, seed=1, sandbox=sandbox)
    assert isinstance(execution, SignalExecution)
    assert execution.dates() == (dt.date(2026, 9, 1), dt.date(2026, 9, 2))
    assert len(execution.vectors) == 2
    for date in execution.dates():
        vector = execution.vector(date)
        assert isinstance(vector, RawScoreVector)
        assert vector.rebalance_date == date


def test_the_sandbox_runs_once_per_date() -> None:
    # "Once per rebalance date" is load-bearing: the loop materializes and runs
    # a fresh window for each date, so the stub is invoked exactly once per
    # date, not once for the whole execution.
    sandbox = StubSandbox()
    execute_signal(_resolution(), _CONFORMING, seed=1, sandbox=sandbox)
    assert len(sandbox.windows) == 2


def test_each_vector_is_sliced_to_its_dates_decision_time() -> None:
    # Each execution runs over the window sliced to that date's decision time —
    # midnight UTC on the rebalance date — so the vector's decision_time names
    # the instant its window was sealed at.
    sandbox = StubSandbox()
    execution = execute_signal(_resolution(), _CONFORMING, seed=1, sandbox=sandbox)
    assert execution.vector(dt.date(2026, 9, 1)).decision_time == dt.datetime(
        2026, 9, 1, tzinfo=dt.timezone.utc
    )
    assert execution.vector(dt.date(2026, 9, 2)).decision_time == dt.datetime(
        2026, 9, 2, tzinfo=dt.timezone.utc
    )


def test_the_vectors_are_keyed_and_immutable() -> None:
    # The map of dates to vectors is a settled record behind a read-only proxy:
    # a caller keeping the dict it passed cannot add a date to a live execution.
    sandbox = StubSandbox()
    execution = execute_signal(_resolution(), _CONFORMING, seed=1, sandbox=sandbox)
    assert execution.vector(dt.date(2026, 9, 2)) is not None
    # An absent date leaks nothing — the miss is reported as None, not a
    # nearest date's scores.
    assert execution.vector(dt.date(2020, 1, 1)) is None
    with pytest.raises(TypeError):
        execution.vectors[dt.date(2026, 9, 3)] = execution.vector(dt.date(2026, 9, 1))


# -- the default materialize reads only surviving partitions ------------------


def test_the_default_materialize_serves_no_date_past_t() -> None:
    # The default materialize builds a window from the resolution's surviving
    # partitions — those at or before the decision time — so a rebalance date
    # past the resolution's ``t`` is never served.  Here the resolution's ``t``
    # is 2026-09-02, and the bars stop there, so both dates are served but a
    # hypothetical 2026-09-03 would have no surviving partition to slice.
    sandbox = StubSandbox()
    execution = execute_signal(_resolution(), _CONFORMING, seed=1, sandbox=sandbox)
    for date in execution.dates():
        vector = execution.vector(date)
        # The universe each vector was scored against is the resolution's —
        # the labels the positional scores align to — resolved, not the wall
        # clock.
        assert vector.universe == ("AAA", "BBB")


def test_an_explicit_rebalance_grid_is_honored() -> None:
    # A caller can pass an explicit rebalance grid to score at a chosen set of
    # dates, rather than the resolution's surviving bars dates.  The loop
    # scores exactly those dates, in ascending order.
    sandbox = StubSandbox()
    grid = (dt.date(2026, 9, 2), dt.date(2026, 9, 1))  # deliberately unsorted
    execution = execute_signal(
        _resolution(), _CONFORMING, seed=1, sandbox=sandbox, rebalance_dates=grid
    )
    assert execution.dates() == (dt.date(2026, 9, 1), dt.date(2026, 9, 2))


def test_no_rebalance_grid_is_refused() -> None:
    # With no rebalance grid — neither passed nor resolvable from surviving
    # bars — the step has nothing to score, which is refused rather than
    # returning an empty execution.
    resolution = WindowResolution(
        snapshot_name="snap_empty",
        t=dt.datetime(2026, 9, 2, tzinfo=dt.timezone.utc),
        universe=("AAA",),
        slices=MappingProxyType({"bars": MappingProxyType({})}),
    )
    with pytest.raises(EvaluatorSignalError, match="rebalance grid"):
        execute_signal(resolution, _CONFORMING, seed=1)


# -- the materialize seam is real ---------------------------------------------


def test_an_injected_materialize_is_used() -> None:
    # The materialize seam turns a (resolution, decision_time) into a window;
    # injecting one proves the loop calls the caller's reader, not a hard-wired
    # one.  The stub returns a fixed window tagged with the decision time, so
    # the test can assert the loop passed each date's instant through.
    seen: list[dt.datetime] = []

    def materialize(resolution: WindowResolution, decision_time: dt.datetime) -> MarketWindow:
        seen.append(decision_time)
        return MarketWindow(decision_time, universe=("AAA", "BBB"), frames={})

    sandbox = StubSandbox()
    execution = execute_signal(
        _resolution(), _CONFORMING, seed=1, sandbox=sandbox, materialize=materialize
    )
    assert sorted(seen) == [
        dt.datetime(2026, 9, 1, tzinfo=dt.timezone.utc),
        dt.datetime(2026, 9, 2, tzinfo=dt.timezone.utc),
    ]
    assert execution.dates() == (dt.date(2026, 9, 1), dt.date(2026, 9, 2))


def test_a_materialize_that_returns_a_non_window_is_refused() -> None:
    # The materialize must produce a window the sandbox can serialize (one
    # exposing to_arrow()).  A reader that returns the wrong shape is refused by
    # name, so the caller learns the seam contract, not a crash in the child.
    def bad_materialize(resolution, decision_time):
        return object()

    with pytest.raises(EvaluatorSignalError, match="to_arrow"):
        execute_signal(
            _resolution(), _CONFORMING, seed=1, materialize=bad_materialize
        )


# -- the identity terms -------------------------------------------------------


def test_the_code_hash_is_sha256_of_the_source() -> None:
    # ``code_hash`` is the sha256 of the signal source — the code's identity,
    # persisted alongside the contract version on the node (§15).  It is stable
    # across runs, so the same source is the same node.
    execution = execute_signal(_resolution(), _CONFORMING, seed=1, sandbox=StubSandbox())
    assert execution.code_hash == hashlib.sha256(_CONFORMING.encode("utf-8")).hexdigest()


def test_the_code_hash_is_stable_and_distinguishes_sources() -> None:
    # Two different sources hash differently; the same source hashes the same —
    # the identity term a persisted result keys on.
    first = execute_signal(_resolution(), _CONFORMING, seed=1, sandbox=StubSandbox())
    again = execute_signal(_resolution(), _CONFORMING, seed=1, sandbox=StubSandbox())
    other = execute_signal(_resolution(), _VIOLATING, seed=1, sandbox=StubSandbox())
    assert first.code_hash == again.code_hash
    assert first.code_hash != other.code_hash


def test_the_snapshot_name_and_seed_travel_on_the_execution() -> None:
    # The execution carries its provenance — the sealed snapshot the window was
    # sliced from — and the seed every vector ran with.
    execution = execute_signal(_resolution(), _CONFORMING, seed=7, sandbox=StubSandbox())
    assert execution.snapshot_name == "snap_abc123"
    assert execution.seed == 7
    for date in execution.dates():
        assert execution.vector(date).seed == 7


# -- the contract is attached but not acted upon ------------------------------


def test_a_violating_return_populates_problems_but_does_not_raise() -> None:
    # A signal that returns the wrong length at a date populates that vector's
    # problems but does not raise — feature 12's consequence is not this
    # feature's.  The raw-score feature records the problem; a downstream
    # feature decides what to do about it.
    sandbox = StubSandbox(fail_class="violation", problems=[_problem("wrong_length")])
    execution = execute_signal(_resolution(), _VIOLATING, seed=1, sandbox=sandbox)
    for date in execution.dates():
        vector = execution.vector(date)
        assert vector.scores is None
        assert [p.kind for p in vector.problems] == ["wrong_length"]
        assert not vector.conforming


def test_a_conforming_vector_reports_conforming() -> None:
    # A conforming vector's ``conforming`` flag is True; a violating one's is
    # False — so a caller can tell "produced a usable vector" from "did not".
    sandbox = StubSandbox()
    execution = execute_signal(_resolution(), _CONFORMING, seed=1, sandbox=sandbox)
    for date in execution.dates():
        assert execution.vector(date).conforming


def _problem(kind: str) -> object:
    """A minimal stand-in for a contract SignalReturnProblem in a stub result."""

    class _P:
        def __init__(self, kind: str) -> None:
            self.kind = kind
            self.message = ""
            self.symbol = None

    return _P(kind)


# -- the real sandbox drives the loop end to end ------------------------------


def test_execute_signal_drives_the_real_sandbox_over_a_resolution() -> None:
    # With no stub, the loop drives the real process sandbox: the signal runs
    # in a child over a window materialized per date, and the raw score vector
    # comes back.  One rebalance date keeps the end-to-end path fast, while
    # still proving the orchestration and the child share the payload channel.
    resolution = WindowResolution(
        snapshot_name="snap_live",
        t=dt.datetime(2026, 9, 1, tzinfo=dt.timezone.utc),
        universe=("AAA", "BBB", "CCC"),
        slices=MappingProxyType(
            {"bars": MappingProxyType({"AAA": ("2026-09-01",),
                                       "BBB": ("2026-09-01",),
                                       "CCC": ("2026-09-01",)})}
        ),
    )
    execution = execute_signal(
        resolution,
        "def signal(ctx, seed):\n    return pl.Series([1.0, 2.0, 3.0])",
        seed=1,
    )
    assert execution.dates() == (dt.date(2026, 9, 1),)
    vector = execution.vector(dt.date(2026, 9, 1))
    assert vector.conforming
    assert vector.scores.to_list() == [1.0, 2.0, 3.0]
    assert vector.contract_version
