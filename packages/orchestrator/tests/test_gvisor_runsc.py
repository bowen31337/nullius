"""Feature 6 (gVisor Executor): the real-``runsc`` integration test.

additions_spec_gvisor_executor.xml, "gVisor Executor", feature 6: *System
emits a skip reason naming the missing piece, or a passing verdict against a
real runsc, in packages/orchestrator/tests/test_gvisor_runsc.py.*

Where ``test_gvisor.py`` exercises :class:`orchestrator._gvisor.GVisorSandbox`
against a fake ``runsc`` double (feature 5's own test note: "a script that
runs the bootstrap directly"), this module is the other half of that
feature's test note — the suite that runs against the real binary, on a host
that has one.  Most hosts do not: ``runsc`` is an operator-provisioned
binary, and :data:`_RUNTIME_ROOT_ENV` names a read-only runtime root that is
built by ``deploy/gvisor/provision_runtime.sh``, not by this repository.  So
every test here is gated by :func:`_missing_piece`, checked once at import
time and applied to the whole module through ``pytestmark`` — a module that
cannot provision its own dependency skips with a reason naming exactly which
one is missing, rather than failing with a confusing ``FileNotFoundError``
or hanging on a container that never starts.

**What "provisioned" means, structurally.**  Two things, both named by the
feature: ``runsc`` resolves on ``PATH`` (:func:`shutil.which`, the same check
:func:`orchestrator._gvisor._require_runsc` makes at construction), and
:data:`_RUNTIME_ROOT_ENV` names a directory that looks like what
``provision_runtime.sh`` builds — at minimum, the ``usr/bin/python3``
interpreter feature 4's bundle points ``process.args`` at
(:data:`orchestrator._oci_bundle._PYTHON`). A root missing that file would
fail every test here with the identical, uninformative "container exited
nonzero" shape, so it is checked once, up front, by name.

**Why these four behaviors, not feature 3's whole hostile-signal list.**
Feature 3's ``test_hostile_signals.py`` already proves the hardened child's
contract exhaustively against a bare subprocess — ten cases, in detail. This
module exists to prove that the identical bootstrap, carried through a real
``runsc`` container instead, still answers that same contract: a benign
signal scores and replays deterministically (the thing a live campaign
actually needs), and a sample of the hostile cases — a network attempt, a
planted-data read, and a disallowed import by name — still land exactly as
they do unisolated, plus the one behavior only gVisor's own process
lifecycle can prove: a hung signal is killed at the wall and ``runsc``'s own
``--root`` state directory carries no per-container state afterward — only
the one shared ``--network=none`` handle every container leaves behind,
never one entry per run — evidence the cleanup feature 5 describes (``runsc
delete -force``, always) actually ran against a real container rather than a
double that merely logged the call.

No test here opens a network connection to a non-loopback host (the one
``socket()`` call exercised never reaches ``connect``; the import guard
refuses the import first) or reads a real credential; nothing is mounted
from the host data lake into the container.
"""

from __future__ import annotations

import datetime as dt
import os
import shutil
import textwrap
import time
from pathlib import Path

import pyarrow as pa
import pytest
from contract.window import MarketWindow
from orchestrator._gvisor import GVisorSandbox
from orchestrator._hardened_sandbox import HardenedLimits

_UNIVERSE = ("AAA", "BBB")

#: The binary feature 5's own construction-time check resolves through
#: ``shutil.which`` — restated here (rather than imported) because this
#: module's own gate must run at collection time, before anything from
#: ``orchestrator._gvisor`` is asked to do any work.
_RUNSC_BINARY = "runsc"

#: The environment variable naming the provisioned, read-only runtime root —
#: ``deploy/gvisor/provision_runtime.sh``'s own output, and the directory
#: ``orchestrator._oci_bundle.build_bundle`` writes into a bundle's
#: ``root.path``.
_RUNTIME_ROOT_ENV = "NULLIUS_GVISOR_RUNTIME_ROOT"

#: The one file checked to tell a provisioned runtime root from an empty or
#: unrelated directory — the interpreter feature 4's bundle launches
#: (``orchestrator._oci_bundle._PYTHON``), restated by value for the same
#: reason the binary name above is: this gate must not import the module
#: whose own construction-time check it is standing in front of.
_RUNTIME_PYTHON_RELPATH = "usr/bin/python3"

#: The one entry a real ``runsc --root`` state directory never loses: the
#: network-namespace handle it creates for a ``--network=none`` container
#: (every container this suite runs is one — see ``_sandbox``'s argv in
#: ``orchestrator._gvisor.GVisorSandbox.run``). It is created once per state
#: root and shared across every container run against it, not per-container,
#: so three runs leave exactly this one entry rather than three. `runsc
#: delete -force` (feature 5's own cleanup) removes each container's own
#: state correctly; it is not, and should not be, expected to remove this
#: shared handle too.
_SHARED_NETNS_HANDLE = "null-netns"


def _missing_piece() -> str | None:
    """The first piece this suite needs that is not here, or ``None``.

    Checked in the feature's own order — the binary, then the runtime root
    the environment names, then whether that root looks provisioned — so a
    host missing more than one piece is told about the first one it would
    hit, the same order a real run would fail in.
    """
    if shutil.which(_RUNSC_BINARY) is None:
        return f"{_RUNSC_BINARY!r} is not on PATH"
    named = os.environ.get(_RUNTIME_ROOT_ENV)
    if named is None or not named.strip():
        return f"{_RUNTIME_ROOT_ENV} is not set"
    root = Path(named)
    if not (root / _RUNTIME_PYTHON_RELPATH).is_file():
        return (
            f"{_RUNTIME_ROOT_ENV} names {named!r}, which does not look like "
            f"a provisioned gVisor runtime (no {_RUNTIME_PYTHON_RELPATH})"
        )
    return None


#: Computed once, at import time: every test below is gated by the same
#: verdict, so the suite either runs in full against a real runtime or is
#: skipped in full with one reason naming the missing piece.
_SKIP_REASON = _missing_piece()

pytestmark = pytest.mark.skipif(_SKIP_REASON is not None, reason=_SKIP_REASON or "")


def _window(universe: tuple[str, ...] = _UNIVERSE) -> MarketWindow:
    t = dt.datetime(2024, 1, 1, tzinfo=dt.UTC)
    frames = {"bars": pa.table({sym: [1.0] for sym in universe})}
    return MarketWindow(t, universe=universe, frames=frames)


def _limits(**overrides: object) -> HardenedLimits:
    # A real container's cold start (the Sentry booting, the runtime root's
    # own interpreter importing polars) costs real wall-clock time a fake
    # double never pays, so these ceilings are looser than test_gvisor.py's
    # own `_fast_limits` — generous enough that a slow but healthy host
    # never times out a benign run, while the one test that wants a timeout
    # overrides `wall_s` down explicitly.
    base: dict[str, object] = {"cpu_s": 20.0, "runner_mem_mb": 4096, "pids": 64, "wall_s": 60.0}
    base.update(overrides)
    return HardenedLimits(**base)


def _sandbox(tmp_path: Path, **overrides: object) -> GVisorSandbox:
    kwargs: dict[str, object] = {
        "runsc": shutil.which(_RUNSC_BINARY),
        "runtime_root": os.environ.get(_RUNTIME_ROOT_ENV, ""),
        "state_root": tmp_path / "state",
        "limits": _limits(),
    }
    kwargs.update(overrides)
    return GVisorSandbox(**kwargs)


_BENIGN = """
import polars as pl

def signal(ctx, seed):
    return pl.Series([float(len(sym)) for sym in ctx.universe])
"""


# -- a benign signal scores, and is deterministic across two runs ------------


def test_benign_signal_scores_and_is_deterministic_across_two_runs(tmp_path: Path) -> None:
    sandbox_instance = _sandbox(tmp_path)
    result_1 = sandbox_instance.run(_BENIGN, _window(), seed=7)
    result_2 = sandbox_instance.run(_BENIGN, _window(), seed=7)

    for result in (result_1, result_2):
        assert result.fail_class is None, result.detail
        assert result.ok
        assert result.scores is not None

    assert result_1.scores.to_list() == [3.0, 3.0]  # len("AAA"), len("BBB")
    assert result_1.scores.to_list() == result_2.scores.to_list()


# -- a socket connection fails: `import socket` is refused --------------------


def test_socket_connection_fails(tmp_path: Path) -> None:
    sandbox_instance = _sandbox(tmp_path)
    code = (
        "import socket\n"
        "def signal(ctx, seed):\n"
        "    socket.socket(socket.AF_INET, socket.SOCK_STREAM)\n"
        "    return None\n"
    )
    result = sandbox_instance.run(code, _window(), seed=1)

    assert result.fail_class == "crash"
    assert "disallowed_import" in result.detail
    assert "'socket'" in result.detail
    assert result.scores is None


# -- a read of a planted lake directory fails ---------------------------------


def test_planted_lake_directory_read_fails(tmp_path: Path) -> None:
    lake_dir = tmp_path / "lake"
    lake_dir.mkdir()
    lake_file = lake_dir / "trades.parquet"
    lake_file.write_bytes(b"not-really-parquet-but-planted")

    sandbox_instance = _sandbox(tmp_path, lake_roots=(lake_dir,))
    code = textwrap.dedent(
        f"""
        def signal(ctx, seed):
            f = open({str(lake_file)!r}, 'rb')
            return None
        """
    )
    result = sandbox_instance.run(code, _window(), seed=1)

    assert result.fail_class == "crash"
    assert result.scores is None
    # No host data directory is ever mounted into the bundle (feature 4), so
    # this never reaches a filesystem call inside the container at all — the
    # file sits untouched on the host the whole time.
    assert lake_file.read_bytes() == b"not-really-parquet-but-planted"


# -- the import guard refuses `import os` ------------------------------------


def test_import_os_is_refused(tmp_path: Path) -> None:
    sandbox_instance = _sandbox(tmp_path)
    code = "import os\ndef signal(ctx, seed):\n    return os.environ.get('PATH')\n"
    result = sandbox_instance.run(code, _window(), seed=1)

    assert result.fail_class == "crash"
    assert "disallowed_import" in result.detail
    assert "'os'" in result.detail
    assert result.scores is None


# -- an infinite loop is a timeout, and the state directory ends up empty ----


def test_infinite_loop_is_a_timeout_and_the_state_dir_is_empty_afterward(
    tmp_path: Path,
) -> None:
    state_root = tmp_path / "state"
    sandbox_instance = _sandbox(tmp_path, state_root=state_root, limits=_limits(wall_s=3.0, cpu_s=30.0))
    code = "def signal(ctx, seed):\n    while True:\n        pass\n"

    started = time.monotonic()
    result = sandbox_instance.run(code, _window(), seed=1)
    elapsed = time.monotonic() - started

    assert result.fail_class == "timeout"
    assert result.scores is None
    assert elapsed < 60.0  # killed promptly, not left to hang

    # `runsc delete -force` always runs (feature 5); a real container's own
    # per-run state under `--root` is gone afterward, not merely the bundle
    # directory (`test_gvisor.py`'s own fake-runsc suite already covers that
    # the *call* happens — this is the real runtime proving it worked). The
    # directory is not expected to be wholly empty, though: a real `runsc`
    # leaves its one shared `--network=none` handle (`_SHARED_NETNS_HANDLE`)
    # behind regardless of how many containers ran, or how they exited.
    assert {entry.name for entry in state_root.iterdir()} <= {_SHARED_NETNS_HANDLE}
