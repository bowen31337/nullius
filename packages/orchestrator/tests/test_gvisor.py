"""Feature 5 (gVisor Executor): ``orchestrator._gvisor.GVisorSandbox``.

additions_spec_gvisor_executor.xml, "gVisor Executor", feature 5:
*System executes a signal under gVisor with orchestrator._gvisor.GVisorSandbox(*,
runsc, runtime_root, state_root, limits=None, lake_roots=()). It is the same
drop-in interface as HardenedSubprocessSandbox.*  Per the feature's own test
note, every test here injects a **fake runsc executable** — a small script
this suite writes and ``chmod +x``'s — never a real, provisioned gVisor
runtime. The fake script does two things real ``runsc`` would: it records
every invocation (argv and environment) under the ``--root`` state directory
it was given, so this suite can assert on them afterward, and for ``run`` it
reads the bundle's own ``config.json``, maps the child bootstrap's in-root
path onto the bundle's own ``root.path`` (the same mapping a real mount
namespace performs for an absolute path inside a container), and execs it
directly — "a script that runs the bootstrap directly", exactly as the
feature's own test note asks for — rather than actually sandboxing anything.
That is enough to exercise :class:`GVisorSandbox`'s whole contract: the exact
argv it launches, the bundle feature 4 built for it, the cleanup it always
performs, and that no variable from this test process's own environment
reaches the spawned command.

bug_spec_gvisor_bind_boot.xml: rootless ``runsc`` cannot boot a sandbox whose
bundle carries a bind mount at all, so the fixture runtime root this suite
builds (:func:`_provision_runtime_root`) carries a real, baked-in copy of
``orchestrator._sandbox_child`` at :data:`CHILD_BOOTSTRAP_PATH` — the same
thing ``deploy/gvisor/provision_runtime.sh`` does for a real runtime — rather
than relying on a bind mount this module no longer produces.

Campaign-driver gaps, "System verifies the gVisor runtime root against its
manifest": construction now also reads ``<runtime_root>.manifest.json`` and
refuses unless its ``tree_sha256`` matches
:func:`orchestrator._gvisor._tree_sha256`'s own recomputation over
``runtime_root`` — so :func:`_provision_runtime_root` writes a correct
manifest too (via :func:`_write_manifest`), the same way
``deploy/gvisor/provision_runtime.sh`` does for a real root, and every
existing construction in this suite keeps passing that check unmodified.
The dedicated tests below build a small fake root (never the real 455 MB
one) and prove a matching digest constructs while a mutated file, a missing
manifest, malformed JSON, a missing ``tree_sha256`` and a wrong digest each
raise :class:`~orchestrator._gvisor.GVisorUnavailableError` — exercised
through a stubbed ``fake_runsc``, never a real one.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import subprocess
import sys
import time
import uuid
from pathlib import Path

import pyarrow as pa
import pytest
from contract.window import MarketWindow
from evaluator import EvaluatorSandboxError, SandboxResult
from orchestrator import _gvisor as gv
from orchestrator import _sandbox_child as _real_child
from orchestrator._hardened_sandbox import HardenedLimits
from orchestrator._oci_bundle import CHILD_BOOTSTRAP_PATH, BundleError

_UNIVERSE = ("AAA", "BBB")

#: Sentinel default for :func:`_write_manifest`'s ``tree_sha256`` keyword,
#: telling "compute the real digest" apart from an explicit ``None`` ("omit
#: the key").
_ABSENT = object()

# -- a provisioned runtime root, the way deploy/gvisor/provision_runtime.sh
# -- bakes one in for real -----------------------------------------------------


def _provision_runtime_root(root: Path) -> Path:
    """Create ``root``, bake in the child bootstrap, and write a matching manifest.

    Mirrors what ``deploy/gvisor/provision_runtime.sh`` does to a real
    runtime root: the child bootstrap lands at :data:`CHILD_BOOTSTRAP_PATH`
    (relative to ``root``), never bind-mounted in at run time, and a
    manifest naming the root's own ``tree_sha256`` is written beside it —
    the digest :class:`~orchestrator._gvisor.GVisorSandbox` now verifies at
    construction. Written last, so it describes the root's final contents.
    """
    root.mkdir(parents=True, exist_ok=True)
    dest = root / CHILD_BOOTSTRAP_PATH.lstrip("/")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(Path(_real_child.__file__).read_bytes())
    _write_manifest(root)
    return root


def _write_manifest(root: Path, *, tree_sha256: object = _ABSENT) -> Path:
    """Write ``<root>.manifest.json``, defaulting ``tree_sha256`` to the real digest.

    ``tree_sha256=None`` omits the key entirely (the "manifest carries no
    tree_sha256" case); any other explicit value is written verbatim (a
    deliberately wrong digest, for the mismatch case).
    """
    digest = gv._tree_sha256(root) if tree_sha256 is _ABSENT else tree_sha256
    manifest: dict[str, object] = {"root": str(root)}
    if digest is not None:
        manifest["tree_sha256"] = digest
    manifest_path = Path(f"{root}.manifest.json")
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    return manifest_path


# -- the fake runsc executables ------------------------------------------------
#
# Both scripts log one JSON line per invocation to ``<state_root>/calls.jsonl``
# — ``{"argv": [...], "env": {...}}``, with a ``"bundle_config"`` key added for
# a ``run`` invocation — so a test can read back exactly what this launcher
# spawned without needing a real container to still exist afterward.
#
# The "proxy" script is the main double: for ``run`` it reads the bundle's
# ``config.json``, finds the bootstrap's in-root path feature 4 wrote into
# ``process.args``, resolves it against the bundle's own ``root.path`` (the
# same mapping a real mount namespace would perform for that absolute path),
# and execs it directly with the *real* interpreter this test suite itself
# runs under (not ``sys.executable`` as the fake script's own process would
# see it — that process is spawned with GVisorSandbox's own stripped
# ``env={"PATH": "/usr/bin:/bin"}``, which would resolve a bare ``python3`` to
# the host's system interpreter, not this workspace's venv — so the real
# interpreter's path is baked into the script's source text at write time
# instead, a fact about the test double, not about the env the launcher
# itself spawns with). It records the bootstrap's pid so a later ``kill``
# invocation of the same script (a separate process) can actually signal it —
# real ``runsc kill`` reaches into gVisor's own process namespace; this
# stand-in has to reach across two of its own host processes instead, which
# is the one thing it does that real runsc would not need to.
_PROXY_RUNSC_SOURCE = '''#!/usr/bin/env python3
import json, os, signal, subprocess, sys
from pathlib import Path

REAL_PYTHON = "__REAL_PYTHON__"


def _flag(argv, name):
    return argv[argv.index(name) + 1]


def main() -> int:
    argv = sys.argv
    state_root = Path(_flag(argv, "--root"))
    state_root.mkdir(parents=True, exist_ok=True)

    entry = {"argv": argv, "env": dict(os.environ)}
    if "run" in argv:
        bundle_dir = Path(_flag(argv, "--bundle"))
        try:
            entry["bundle_config"] = json.loads((bundle_dir / "config.json").read_text(encoding="utf-8"))
        except OSError:
            entry["bundle_config"] = None

    with (state_root / "calls.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry) + "\\n")

    if "run" in argv:
        container_id = argv[-1]
        config = entry["bundle_config"]
        root_path = config["root"]["path"]
        child_in_root = config["process"]["args"][-1].lstrip("/")
        child_path = str(Path(root_path) / child_in_root)
        proc = subprocess.Popen(
            [REAL_PYTHON, "-I", child_path],
            stdin=sys.stdin.fileno(),
            stdout=sys.stdout.fileno(),
            stderr=sys.stderr.fileno(),
        )
        pid_path = state_root / (container_id + ".pid")
        pid_path.write_text(str(proc.pid), encoding="utf-8")
        returncode = proc.wait()
        try:
            pid_path.unlink()
        except FileNotFoundError:
            pass
        return returncode

    if "kill" in argv:
        container_id = argv[argv.index("kill") + 1]
        pid_path = state_root / (container_id + ".pid")
        try:
            pid = int(pid_path.read_text(encoding="utf-8"))
            os.kill(pid, signal.SIGKILL)
        except (FileNotFoundError, ValueError, ProcessLookupError):
            pass
        return 0

    return 0


if __name__ == "__main__":
    sys.exit(main())
'''

# A second, dedicated double for the one test that needs runsc to report a
# sandbox violation: it never spawns a bootstrap at all, it just writes a
# marker this suite controls to its own stderr and exits non-zero.
_VIOLATION_RUNSC_SOURCE = '''#!/usr/bin/env python3
import json, os, sys
from pathlib import Path


def _flag(argv, name):
    return argv[argv.index(name) + 1]


def main() -> int:
    argv = sys.argv
    state_root = Path(_flag(argv, "--root"))
    state_root.mkdir(parents=True, exist_ok=True)
    with (state_root / "calls.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({"argv": argv, "env": dict(os.environ)}) + "\\n")

    if "run" in argv:
        sys.stderr.write("FATAL ERROR: sandbox violation: synthetic seccomp violation for test\\n")
        sys.stderr.flush()
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
'''


def _write_script(path: Path, source: str) -> Path:
    path.write_text(source, encoding="utf-8")
    path.chmod(0o755)
    return path


@pytest.fixture
def fake_runsc(tmp_path: Path) -> Path:
    source = _PROXY_RUNSC_SOURCE.replace("__REAL_PYTHON__", sys.executable)
    return _write_script(tmp_path / "fake_runsc", source)


@pytest.fixture
def violation_runsc(tmp_path: Path) -> Path:
    return _write_script(tmp_path / "violation_runsc", _VIOLATION_RUNSC_SOURCE)


def _calls(state_root: Path) -> list[dict]:
    log_path = state_root / "calls.jsonl"
    if not log_path.is_file():
        return []
    return [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines() if line]


def _window(universe: tuple[str, ...] = _UNIVERSE) -> MarketWindow:
    t = dt.datetime(2024, 1, 1, tzinfo=dt.UTC)
    frames = {"bars": pa.table({sym: [1.0] for sym in universe})}
    return MarketWindow(t, universe=universe, frames=frames)


def _fast_limits(**overrides: object) -> HardenedLimits:
    base: dict[str, object] = {"cpu_s": 10.0, "runner_mem_mb": 4096, "pids": 64, "wall_s": 10.0}
    base.update(overrides)
    return HardenedLimits(**base)


def _sandbox(tmp_path: Path, runsc: Path, **overrides: object) -> gv.GVisorSandbox:
    runtime_root = Path(overrides.pop("runtime_root", tmp_path / "runtime-root"))
    _provision_runtime_root(runtime_root)
    kwargs: dict[str, object] = {
        "runsc": str(runsc),
        "runtime_root": runtime_root,
        "state_root": tmp_path / "state",
        "limits": _fast_limits(),
        "lake_roots": (),
    }
    kwargs.update(overrides)
    return gv.GVisorSandbox(**kwargs)


_BENIGN = """
import polars as pl

def signal(ctx, seed):
    return pl.Series([float(len(sym)) for sym in ctx.universe])
"""


# -- construction: a missing or non-executable runsc is refused ---------------


def test_missing_runsc_raises_gvisor_unavailable(tmp_path: Path) -> None:
    with pytest.raises(gv.GVisorUnavailableError, match=gv.GVISOR_UNAVAILABLE_CODE):
        gv.GVisorSandbox(
            runsc=str(tmp_path / "does-not-exist"),
            runtime_root=tmp_path / "runtime-root",
            state_root=tmp_path / "state",
        )


def test_non_executable_runsc_raises_gvisor_unavailable(tmp_path: Path) -> None:
    not_executable = tmp_path / "runsc-but-not-executable"
    not_executable.write_text("#!/usr/bin/env python3\n", encoding="utf-8")
    not_executable.chmod(0o644)
    with pytest.raises(gv.GVisorUnavailableError, match=gv.GVISOR_UNAVAILABLE_CODE):
        gv.GVisorSandbox(
            runsc=str(not_executable),
            runtime_root=tmp_path / "runtime-root",
            state_root=tmp_path / "state",
        )


def test_a_directory_at_the_runsc_path_is_not_executable(tmp_path: Path) -> None:
    a_directory = tmp_path / "runsc-is-actually-a-directory"
    a_directory.mkdir()
    with pytest.raises(gv.GVisorUnavailableError, match=gv.GVISOR_UNAVAILABLE_CODE):
        gv.GVisorSandbox(
            runsc=str(a_directory),
            runtime_root=tmp_path / "runtime-root",
            state_root=tmp_path / "state",
        )


# -- construction: a runtime root missing the baked-in child is refused ------


def test_missing_child_bootstrap_raises_gvisor_unavailable(tmp_path: Path, fake_runsc: Path) -> None:
    runtime_root = tmp_path / "runtime-root"
    runtime_root.mkdir()  # provisioned enough to exist, but no child bootstrap baked in
    with pytest.raises(gv.GVisorUnavailableError, match=gv.GVISOR_UNAVAILABLE_CODE) as excinfo:
        gv.GVisorSandbox(
            runsc=str(fake_runsc),
            runtime_root=runtime_root,
            state_root=tmp_path / "state",
        )
    assert CHILD_BOOTSTRAP_PATH in str(excinfo.value)


def test_an_unprovisioned_runtime_root_is_refused_the_same_way(tmp_path: Path, fake_runsc: Path) -> None:
    with pytest.raises(gv.GVisorUnavailableError, match=gv.GVISOR_UNAVAILABLE_CODE):
        gv.GVisorSandbox(
            runsc=str(fake_runsc),
            runtime_root=tmp_path / "does" / "not" / "exist",
            state_root=tmp_path / "state",
        )


# -- construction: the runtime root must match its own manifest's digest -----
#
# None of these need a real runsc — fake_runsc (feature 5's stand-in,
# resolved via shutil.which exactly like the real binary) is enough, because
# the manifest check runs before anything is ever spawned. The direct
# _tree_sha256 tests below need no runsc at all, run or stubbed.


def test_tree_sha256_pure_function_matches_hand_computed_digest(tmp_path: Path) -> None:
    root = tmp_path / "tiny-root"
    (root / "a").mkdir(parents=True)
    (root / "a" / "one.txt").write_bytes(b"one")
    (root / "two.txt").write_bytes(b"two")
    (root / "a" / "a-link.txt").symlink_to(root / "a" / "one.txt")  # excluded, like `find -type f`

    lines = [
        f"{hashlib.sha256(b'one').hexdigest()}  ./a/one.txt\n",
        f"{hashlib.sha256(b'two').hexdigest()}  ./two.txt\n",
    ]
    expected = hashlib.sha256("".join(lines).encode("utf-8")).hexdigest()
    assert gv._tree_sha256(root) == expected


def test_tree_sha256_matches_the_shell_pipeline_provision_runtime_sh_uses(tmp_path: Path) -> None:
    root = tmp_path / "tiny-root"
    (root / "nested").mkdir(parents=True)
    (root / "nested" / "B.txt").write_bytes(b"content-b")
    (root / "a.txt").write_bytes(b"content-a")

    shell_digest = subprocess.run(
        "find . -type f -perm -004 -print0 | LC_ALL=C sort -z | xargs -0 sha256sum | sha256sum | cut -d' ' -f1",
        shell=True,
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    assert gv._tree_sha256(root) == shell_digest


def test_tree_sha256_ignores_a_root_only_file(tmp_path: Path) -> None:
    # The bug this guards: a provisioned runtime root carries files like
    # /etc/shadow at mode 0600, readable only by root. _tree_sha256 must
    # select on the other-read bit alone (never on whether open() would
    # actually succeed), so root (provisioning) and a non-root launcher
    # (verifying) land on the identical digest.
    root = tmp_path / "tiny-root"
    root.mkdir()
    (root / "world-readable.txt").write_bytes(b"readable")
    root_only = root / "root-only.txt"
    root_only.write_bytes(b"secret")
    root_only.chmod(0o600)

    lines = [f"{hashlib.sha256(b'readable').hexdigest()}  ./world-readable.txt\n"]
    expected = hashlib.sha256("".join(lines).encode("utf-8")).hexdigest()
    assert gv._tree_sha256(root) == expected

    # changing the root-only file's content does not move the digest
    root_only.write_bytes(b"a-different-secret")
    assert gv._tree_sha256(root) == expected

    # nor does removing it outright
    root_only.unlink()
    assert gv._tree_sha256(root) == expected


def test_tree_sha256_still_reacts_to_a_changed_world_readable_file(tmp_path: Path) -> None:
    root = tmp_path / "tiny-root"
    root.mkdir()
    readable = root / "world-readable.txt"
    readable.write_bytes(b"one")
    before = gv._tree_sha256(root)

    readable.write_bytes(b"two")
    after = gv._tree_sha256(root)

    assert before != after


def test_tree_sha256_does_not_raise_permission_error_on_an_unreadable_file(tmp_path: Path) -> None:
    root = tmp_path / "tiny-root"
    root.mkdir()
    (root / "world-readable.txt").write_bytes(b"readable")
    unreadable = root / "unreadable.txt"
    unreadable.write_bytes(b"secret")
    unreadable.chmod(0o000)  # not even the owner can read it, like a root-only file to a non-root verifier

    gv._tree_sha256(root)  # must not raise PermissionError


def test_a_fresh_manifest_with_a_matching_digest_constructs(tmp_path: Path, fake_runsc: Path) -> None:
    sandbox_instance = _sandbox(tmp_path, fake_runsc)
    assert isinstance(sandbox_instance, gv.GVisorSandbox)


def test_construction_against_a_root_only_file_does_not_raise_permission_error(
    tmp_path: Path, fake_runsc: Path
) -> None:
    # bug_spec_gvisor_root_only_digest.xml: a real provisioned root carries a
    # handful of root-only files (mode 0600, owned by root) that the
    # non-root launcher cannot open. Mode 0o000 reproduces the same "this
    # process cannot read it" fact without needing an actual root-owned
    # file — even the owner has no read bit, so a naive read would raise
    # PermissionError exactly as it does against a real debootstrap root.
    runtime_root = tmp_path / "runtime-root"
    _provision_runtime_root(runtime_root)
    root_only = runtime_root / "etc" / "shadow"
    root_only.parent.mkdir(parents=True, exist_ok=True)
    root_only.write_bytes(b"root:!:19000:0:99999:7:::\n")
    root_only.chmod(0o000)
    _write_manifest(runtime_root)  # recomputed with the root-only file present, but excluded from the digest

    sandbox_instance = gv.GVisorSandbox(
        runsc=str(fake_runsc), runtime_root=runtime_root, state_root=tmp_path / "state"
    )
    assert isinstance(sandbox_instance, gv.GVisorSandbox)


def test_a_mutated_file_after_the_manifest_was_written_is_refused(tmp_path: Path, fake_runsc: Path) -> None:
    runtime_root = tmp_path / "runtime-root"
    _provision_runtime_root(runtime_root)
    (runtime_root / CHILD_BOOTSTRAP_PATH.lstrip("/")).write_bytes(b"tampered-after-provisioning")
    with pytest.raises(gv.GVisorUnavailableError, match=gv.GVISOR_UNAVAILABLE_CODE) as excinfo:
        gv.GVisorSandbox(runsc=str(fake_runsc), runtime_root=runtime_root, state_root=tmp_path / "state")
    assert str(runtime_root) in str(excinfo.value)


def test_a_missing_manifest_file_is_refused(tmp_path: Path, fake_runsc: Path) -> None:
    runtime_root = tmp_path / "runtime-root"
    runtime_root.mkdir()
    dest = runtime_root / CHILD_BOOTSTRAP_PATH.lstrip("/")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(Path(_real_child.__file__).read_bytes())
    # deliberately no manifest written at all
    with pytest.raises(gv.GVisorUnavailableError, match=gv.GVISOR_UNAVAILABLE_CODE) as excinfo:
        gv.GVisorSandbox(runsc=str(fake_runsc), runtime_root=runtime_root, state_root=tmp_path / "state")
    assert "manifest" in str(excinfo.value)


def test_malformed_manifest_json_is_refused(tmp_path: Path, fake_runsc: Path) -> None:
    runtime_root = tmp_path / "runtime-root"
    _provision_runtime_root(runtime_root)
    Path(f"{runtime_root}.manifest.json").write_text("{not valid json", encoding="utf-8")
    with pytest.raises(gv.GVisorUnavailableError, match=gv.GVISOR_UNAVAILABLE_CODE) as excinfo:
        gv.GVisorSandbox(runsc=str(fake_runsc), runtime_root=runtime_root, state_root=tmp_path / "state")
    assert str(runtime_root) in str(excinfo.value)


def test_manifest_missing_tree_sha256_key_is_refused(tmp_path: Path, fake_runsc: Path) -> None:
    runtime_root = tmp_path / "runtime-root"
    _provision_runtime_root(runtime_root)
    _write_manifest(runtime_root, tree_sha256=None)
    with pytest.raises(gv.GVisorUnavailableError, match=gv.GVISOR_UNAVAILABLE_CODE) as excinfo:
        gv.GVisorSandbox(runsc=str(fake_runsc), runtime_root=runtime_root, state_root=tmp_path / "state")
    assert "tree_sha256" in str(excinfo.value)


def test_a_wrong_tree_sha256_in_the_manifest_is_refused(tmp_path: Path, fake_runsc: Path) -> None:
    runtime_root = tmp_path / "runtime-root"
    _provision_runtime_root(runtime_root)
    _write_manifest(runtime_root, tree_sha256="0" * 64)
    with pytest.raises(gv.GVisorUnavailableError, match=gv.GVISOR_UNAVAILABLE_CODE) as excinfo:
        gv.GVisorSandbox(runsc=str(fake_runsc), runtime_root=runtime_root, state_root=tmp_path / "state")
    message = str(excinfo.value)
    assert "0" * 64 in message
    assert str(runtime_root) in message


def test_runsc_as_a_path_object_not_just_a_string(tmp_path: Path, fake_runsc: Path) -> None:
    # PathLike means a Path works too, not just str — for every one of the
    # three path-shaped constructor keywords.
    runtime_root = _provision_runtime_root(tmp_path / "runtime-root")
    sandbox_instance = gv.GVisorSandbox(
        runsc=fake_runsc,
        runtime_root=runtime_root,
        state_root=tmp_path / "state",
    )
    result = sandbox_instance.run(_BENIGN, _window(), seed=1)
    assert result.ok


def test_construction_creates_the_state_root(tmp_path: Path, fake_runsc: Path) -> None:
    state_root = tmp_path / "does" / "not" / "exist" / "yet"
    _sandbox(tmp_path, fake_runsc, state_root=state_root)
    assert state_root.is_dir()


def test_default_limits_come_from_the_sandbox_member_policies(tmp_path: Path, fake_runsc: Path) -> None:
    import sandbox
    from orchestrator._hardened_sandbox import _default_limits

    runtime_root = _provision_runtime_root(tmp_path / "runtime-root")
    sandbox_instance = gv.GVisorSandbox(
        runsc=str(fake_runsc),
        runtime_root=runtime_root,
        state_root=tmp_path / "state",
    )
    assert sandbox_instance.limits == _default_limits()
    assert isinstance(sandbox.committed_budget_policy().value("cpu_s"), (int, float))  # policy actually read


# -- disallowed imports never touch the bundle or runsc ------------------------


def test_disallowed_import_answers_crash_without_spawning_runsc(tmp_path: Path, fake_runsc: Path) -> None:
    sandbox_instance = _sandbox(tmp_path, fake_runsc)
    code = "import os\ndef signal(ctx, seed):\n    return None\n"
    result = sandbox_instance.run(code, _window(), seed=1)

    assert result.fail_class == "crash"
    assert "disallowed_import" in result.detail
    assert result.scores is None
    assert result.seed == 1
    assert _calls(tmp_path / "state") == []  # no process spawned at all


def test_a_window_without_to_arrow_raises_and_spawns_nothing(tmp_path: Path, fake_runsc: Path) -> None:
    sandbox_instance = _sandbox(tmp_path, fake_runsc)
    with pytest.raises(EvaluatorSandboxError):
        sandbox_instance.run("def signal(ctx, seed):\n    return None\n", object(), seed=1)
    assert _calls(tmp_path / "state") == []


# -- a benign signal scores, through the fake runsc and the real bootstrap ----


def test_benign_signal_scores_and_is_deterministic(tmp_path: Path, fake_runsc: Path) -> None:
    sandbox_instance = _sandbox(tmp_path, fake_runsc)
    result_1 = sandbox_instance.run(_BENIGN, _window(), seed=7)
    result_2 = sandbox_instance.run(_BENIGN, _window(), seed=7)

    for result in (result_1, result_2):
        assert isinstance(result, SandboxResult)
        assert result.fail_class is None
        assert result.ok
        assert result.seed == 7
        assert result.contract_version

    assert result_1.scores.to_list() == [3.0, 3.0]
    assert result_1.scores.to_list() == result_2.scores.to_list()


def test_scores_are_positional_against_the_universe(tmp_path: Path, fake_runsc: Path) -> None:
    sandbox_instance = _sandbox(tmp_path, fake_runsc)
    result = sandbox_instance.run(_BENIGN, _window(("AAA", "BBBB", "C")), seed=1)
    assert result.scores.to_list() == [3.0, 4.0, 1.0]


# -- the exact argv runsc is launched with -------------------------------------


def test_exact_argv_for_run(tmp_path: Path, fake_runsc: Path) -> None:
    state_root = tmp_path / "state"
    sandbox_instance = _sandbox(tmp_path, fake_runsc, state_root=state_root)
    sandbox_instance.run(_BENIGN, _window(), seed=1)

    run_calls = [c for c in _calls(state_root) if "run" in c["argv"]]
    assert len(run_calls) == 1
    argv = run_calls[0]["argv"]

    assert argv[0] == str(fake_runsc)
    assert argv[1] == "--rootless"
    assert argv[2] == "--network=none"
    assert argv[3] == "--root"
    assert argv[4] == str(state_root)
    assert argv[5] == "run"
    assert argv[6] == "--bundle"
    # argv[7] is the ephemeral bundle directory — only its shape is checked.
    assert "nullius-gvisor-bundle-" in argv[7]
    container_id = argv[8]
    assert uuid.UUID(container_id).version == 4
    assert len(argv) == 9


def test_no_environment_variable_from_the_parent_leaks(
    tmp_path: Path, fake_runsc: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("NULLIUS_TEST_SECRET", "do-not-leak")
    state_root = tmp_path / "state"
    sandbox_instance = _sandbox(tmp_path, fake_runsc, state_root=state_root)
    result = sandbox_instance.run(_BENIGN, _window(), seed=1)
    assert result.ok

    calls = _calls(state_root)
    assert len(calls) >= 2  # at least a run and a delete
    for call in calls:
        env = call["env"]
        assert env["PATH"] == "/usr/bin:/bin"
        # A fake runsc written in Python is itself a CPython process, and
        # CPython's own startup (PEP 538) coerces a bare "C" locale by adding
        # LC_CTYPE/LANG to *its own* os.environ once running — an artifact of
        # the double being Python, not a leak through GVisorSandbox's env=.
        # Anything else present would be the leak this test exists to catch.
        leaked = set(env) - {"PATH", "LC_CTYPE", "LANG", "LC_ALL"}
        assert not leaked, f"unexpected environment keys reached the spawned command: {leaked}"
        assert "NULLIUS_TEST_SECRET" not in env
        assert "do-not-leak" not in json.dumps(env)


# -- the bundle contents match feature 4's own contract (post-fix shape) ------


def test_bundle_contents_match_feature_4(tmp_path: Path, fake_runsc: Path) -> None:
    state_root = tmp_path / "state"
    runtime_root = tmp_path / "runtime-root"
    limits = _fast_limits(runner_mem_mb=2048, pids=16)
    sandbox_instance = _sandbox(
        tmp_path, fake_runsc, state_root=state_root, runtime_root=runtime_root, limits=limits
    )
    sandbox_instance.run(_BENIGN, _window(), seed=1)

    run_calls = [c for c in _calls(state_root) if "run" in c["argv"]]
    config = run_calls[0]["bundle_config"]

    assert config["process"]["args"] == ["/usr/bin/python3", "-I", CHILD_BOOTSTRAP_PATH]
    assert config["process"]["env"] == [
        "PATH=/usr/bin:/bin",
        "OMP_NUM_THREADS=1",
        "MKL_NUM_THREADS=1",
        "POLARS_MAX_THREADS=1",
        "PYTHONHASHSEED=0",
    ]
    assert all(not var.startswith("NULLIUS_SIGNAL_SEED") for var in config["process"]["env"])
    assert config["root"] == {"path": str(runtime_root.resolve()), "readonly": True}

    # The regression this bug fixes: no mount carries the child bootstrap (or
    # anything else) as a bind — rootless runsc cannot boot a sandbox whose
    # bundle carries one at all (bug_spec_gvisor_bind_boot.xml).
    destinations = {m["destination"] for m in config["mounts"]}
    assert destinations == {"/proc", "/dev", "/sys", "/tmp"}
    assert all(m["type"] != "bind" for m in config["mounts"])

    assert config["linux"]["resources"]["memory"]["limit"] == 2048 * 1024 * 1024
    assert config["linux"]["resources"]["pids"]["limit"] == 16


def test_lake_root_misconfiguration_propagates_as_bundle_error(tmp_path: Path, fake_runsc: Path) -> None:
    lake_root = tmp_path / "lake"
    runtime_root = lake_root / "runtime-root"
    sandbox_instance = _sandbox(tmp_path, fake_runsc, runtime_root=runtime_root, lake_roots=(lake_root,))
    with pytest.raises(BundleError):
        sandbox_instance.run(_BENIGN, _window(), seed=1)


# -- cleanup always runs, regardless of outcome --------------------------------


def test_cleanup_always_deletes_the_container_on_success(tmp_path: Path, fake_runsc: Path) -> None:
    state_root = tmp_path / "state"
    sandbox_instance = _sandbox(tmp_path, fake_runsc, state_root=state_root)
    sandbox_instance.run(_BENIGN, _window(), seed=1)

    run_calls = [c for c in _calls(state_root) if "run" in c["argv"]]
    delete_calls = [c for c in _calls(state_root) if "delete" in c["argv"]]
    assert len(delete_calls) == 1
    container_id = run_calls[0]["argv"][-1]
    assert delete_calls[0]["argv"] == [
        str(fake_runsc),
        "--rootless",
        "--root",
        str(state_root),
        "delete",
        "-force",
        container_id,
    ]

    # the bundle directory itself is also gone afterward
    assert not Path(run_calls[0]["argv"][7]).exists()


def test_cleanup_runs_even_when_the_bundle_build_itself_is_refused(tmp_path: Path, fake_runsc: Path) -> None:
    # No container is ever created here (build_bundle raises before runsc is
    # ever spawned to "run"), but "always runs runsc delete -force" still
    # means a delete call for the generated container id — a no-op against a
    # runtime that never heard of it, and harmless for exactly that reason.
    state_root = tmp_path / "state"
    lake_root = tmp_path / "lake"
    runtime_root = lake_root / "runtime-root"
    sandbox_instance = _sandbox(
        tmp_path, fake_runsc, state_root=state_root, runtime_root=runtime_root, lake_roots=(lake_root,)
    )
    with pytest.raises(BundleError):
        sandbox_instance.run(_BENIGN, _window(), seed=1)

    calls = _calls(state_root)
    assert all("run" not in c["argv"] for c in calls)  # never reached runsc run
    delete_calls = [c for c in calls if "delete" in c["argv"]]
    assert len(delete_calls) == 1
    assert "-force" in delete_calls[0]["argv"]
    assert uuid.UUID(delete_calls[0]["argv"][-1]).version == 4


def test_cleanup_always_deletes_the_container_on_crash(tmp_path: Path, fake_runsc: Path) -> None:
    state_root = tmp_path / "state"
    sandbox_instance = _sandbox(tmp_path, fake_runsc, state_root=state_root)
    code = "def signal(ctx, seed):\n    raise ValueError('boom')\n"
    result = sandbox_instance.run(code, _window(), seed=1)

    assert result.fail_class == "crash"
    assert "boom" in result.detail
    delete_calls = [c for c in _calls(state_root) if "delete" in c["argv"]]
    assert len(delete_calls) == 1


# -- the signal contract runs in the container, as values, not raises --------


def test_a_signal_that_raises_is_a_crash(tmp_path: Path, fake_runsc: Path) -> None:
    sandbox_instance = _sandbox(tmp_path, fake_runsc)
    code = "def signal(ctx, seed):\n    raise ValueError('boom')\n"
    result = sandbox_instance.run(code, _window(), seed=1)
    assert result.fail_class == "crash"
    assert result.scores is None
    assert "boom" in result.detail


def test_a_wrong_length_return_is_a_violation_with_problems(tmp_path: Path, fake_runsc: Path) -> None:
    sandbox_instance = _sandbox(tmp_path, fake_runsc)
    code = "import polars as pl\ndef signal(ctx, seed):\n    return pl.Series([1.0])\n"
    result = sandbox_instance.run(code, _window(), seed=1)
    assert result.fail_class == "violation"
    assert result.scores is None
    assert [p.kind for p in result.problems] == ["wrong_length"]


# -- the wall-clock watchdog kills through `runsc kill` ------------------------


def test_a_signal_that_never_yields_is_killed_at_the_wall(tmp_path: Path, fake_runsc: Path) -> None:
    state_root = tmp_path / "state"
    sandbox_instance = _sandbox(tmp_path, fake_runsc, state_root=state_root, limits=_fast_limits(wall_s=1.0))
    code = "def signal(ctx, seed):\n    while True:\n        pass\n"
    started = time.monotonic()
    result = sandbox_instance.run(code, _window(), seed=1)
    elapsed = time.monotonic() - started

    assert result.fail_class == "timeout"
    assert result.scores is None
    assert elapsed < 15.0  # killed promptly, not left to hang

    run_calls = [c for c in _calls(state_root) if "run" in c["argv"]]
    container_id = run_calls[0]["argv"][-1]
    kill_calls = [c for c in _calls(state_root) if "kill" in c["argv"]]
    assert len(kill_calls) == 1
    assert kill_calls[0]["argv"] == [
        str(fake_runsc),
        "--rootless",
        "--root",
        str(state_root),
        "kill",
        container_id,
        "SIGKILL",
    ]
    delete_calls = [c for c in _calls(state_root) if "delete" in c["argv"]]
    assert len(delete_calls) == 1  # cleanup still ran after the kill


# -- runsc reporting a sandbox violation is its own fail class ----------------


def test_runsc_reported_violation_is_sandbox_escape(tmp_path: Path, violation_runsc: Path) -> None:
    sandbox_instance = _sandbox(tmp_path, violation_runsc)
    result = sandbox_instance.run(_BENIGN, _window(), seed=1)
    assert result.fail_class == "sandbox_escape"
    assert "sandbox violation" in result.detail
    assert result.scores is None


@pytest.mark.parametrize(
    ("stderr", "expected"),
    [
        (b"FATAL ERROR: sandbox violation: foo", True),
        (b"a seccomp violation was reported", True),
        (b"terminated by bad system call", True),
        (b"killed by SIGSYS", True),
        (b"ordinary stack trace, nothing special", False),
        (b"", False),
    ],
)
def test_reports_sandbox_violation_is_a_pure_marker_check(stderr: bytes, expected: bool) -> None:
    assert gv._reports_sandbox_violation(stderr) is expected
