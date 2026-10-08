"""Bug fix (bug_spec_gvisor_runtime_staleness.xml): a stale gVisor runtime root.

``orchestrator._gvisor._require_matching_manifest`` only proves a runtime
root is internally intact — that its own contents still hash to what its own
manifest recorded at provisioning time. It proves nothing about whether that
content is still what the *host* ships: a root baked from an older checkout
passes that check forever, even once ``packages/contract``, ``src/app`` or
``orchestrator/_sandbox_child.py`` have moved on since. GV-STALE-1: the root
provisioned 2026-10-06 kept serving contract 0.1.0's frame-wide bars lookback
long after the host (423598f) and the prompt moved to 0.2.0's per-symbol
rule — every such signal failed as constant scores, and every failure was a
charged trial.

This module exercises ``orchestrator._gvisor._require_current_runtime_sources``,
the other half of the manifest's contract: it recomputes the same three
source digests from the host's own sources — located through
``_host_contract_dir``, ``_host_app_dir`` and ``_host_child_bootstrap_path``,
monkeypatched here to point at small fixture trees rather than this
repository's real ``packages/contract`` and ``src/app``, so a test can
"edit the host's contract" without touching a real file this process also
imports from — and refuses construction when any of them disagrees with the
manifest's recording.

Needs no ``runsc`` and no ``sudo``: both the tree-digest and the
source-digest checks run at construction, before anything is ever spawned.
No module-level state is kept across tests, so this passes under
pytest-xdist like the rest of the suite.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest
from orchestrator import _gvisor as gv
from orchestrator import _sandbox_child as _real_child
from orchestrator._oci_bundle import CHILD_BOOTSTRAP_PATH

_ABSENT = object()


# -- fixture scaffolding: a fake runtime root, a fake "host", and a manifest -


def _write_script(path: Path, source: str) -> Path:
    path.write_text(source, encoding="utf-8")
    path.chmod(0o755)
    return path


@pytest.fixture
def fake_runsc(tmp_path: Path) -> Path:
    # Never actually invoked: every check this module exercises runs at
    # construction, before GVisorSandbox.run ever spawns anything.
    return _write_script(tmp_path / "fake_runsc", "#!/usr/bin/env python3\nraise SystemExit(1)\n")


def _provision_runtime_root(root: Path) -> Path:
    """The pieces ``_require_child_bootstrap``/``_require_matching_manifest`` need.

    Mirrors ``deploy/gvisor/provision_runtime.sh``'s layout just enough for
    those two (unchanged) checks to pass — the baked child bootstrap at
    :data:`CHILD_BOOTSTRAP_PATH`. The manifest is written separately, by
    :func:`_write_manifest`, once the fixture "host" sources it should agree
    with are known.
    """
    root.mkdir(parents=True, exist_ok=True)
    dest = root / CHILD_BOOTSTRAP_PATH.lstrip("/")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(Path(_real_child.__file__).read_bytes())
    return root


def _write_manifest(
    root: Path,
    *,
    contract_source_sha256: object = _ABSENT,
    app_source_sha256: object = _ABSENT,
    child_bootstrap_sha256: object = _ABSENT,
    contract_version: object = "0.1.0",
    omit: tuple[str, ...] = (),
) -> Path:
    """Write ``<root>.manifest.json``, ``tree_sha256`` always the real digest.

    Each staleness field defaults to ``_ABSENT``, meaning "leave it out" —
    callers that want the guard's new fields present pass them explicitly
    (normally the current digest of the fixture "host" dir, from
    :func:`_source_digests`), while a test proving the missing-fields path
    simply writes none of them.
    """
    manifest: dict[str, object] = {"root": str(root), "tree_sha256": gv._tree_sha256(root)}
    supplied = {
        "contract_source_sha256": contract_source_sha256,
        "app_source_sha256": app_source_sha256,
        "child_bootstrap_sha256": child_bootstrap_sha256,
        "contract_version": contract_version,
    }
    for key, value in supplied.items():
        if value is not _ABSENT:
            manifest[key] = value
    for key in omit:
        manifest.pop(key, None)
    manifest_path = Path(f"{root}.manifest.json")
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    return manifest_path


@dataclass
class _HostSources:
    contract_dir: Path
    app_dir: Path
    child_path: Path

    def digests(self) -> dict[str, str]:
        return {
            "contract_source_sha256": gv._source_tree_sha256(self.contract_dir),
            "app_source_sha256": gv._source_tree_sha256(self.app_dir),
            "child_bootstrap_sha256": hashlib.sha256(self.child_path.read_bytes()).hexdigest(),
        }


@pytest.fixture
def host_sources(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> _HostSources:
    """A fake "host" contract/app/child, standing in for this repo's real ones.

    :class:`~orchestrator._gvisor.GVisorSandbox` locates the host's sources
    through :func:`orchestrator._gvisor._host_contract_dir`,
    :func:`~orchestrator._gvisor._host_app_dir` and
    :func:`~orchestrator._gvisor._host_child_bootstrap_path` — monkeypatched
    here to resolve to these fixture trees instead of this process's own
    ``packages/contract``, ``src/app`` and
    ``orchestrator/_sandbox_child.py``, so a test can simulate "the host's
    contract changed since this root was provisioned" by editing a file in
    ``tmp_path`` rather than this repository's real source tree.
    """
    contract_dir = tmp_path / "host" / "contract"
    contract_dir.mkdir(parents=True)
    (contract_dir / "__init__.py").write_text('CONTRACT_VERSION = "0.2.0"\n', encoding="utf-8")
    (contract_dir / "payload.py").write_text("PAYLOAD_VERSION = 1\n", encoding="utf-8")

    app_dir = tmp_path / "host" / "app"
    app_dir.mkdir(parents=True)
    (app_dir / "module_loader.py").write_text("# module loader\n", encoding="utf-8")

    child_path = tmp_path / "host" / "_sandbox_child.py"
    child_path.write_bytes(Path(_real_child.__file__).read_bytes())

    monkeypatch.setattr(gv, "_host_contract_dir", lambda: contract_dir)
    monkeypatch.setattr(gv, "_host_app_dir", lambda: app_dir)
    monkeypatch.setattr(gv, "_host_child_bootstrap_path", lambda: child_path)

    return _HostSources(contract_dir=contract_dir, app_dir=app_dir, child_path=child_path)


def _sandbox(tmp_path: Path, runsc: Path, runtime_root: Path) -> gv.GVisorSandbox:
    return gv.GVisorSandbox(runsc=str(runsc), runtime_root=runtime_root, state_root=tmp_path / "state")


# -- matching digests construct fine ------------------------------------------


def test_matching_source_digests_construct_fine(
    tmp_path: Path, fake_runsc: Path, host_sources: _HostSources
) -> None:
    runtime_root = _provision_runtime_root(tmp_path / "runtime-root")
    _write_manifest(runtime_root, **host_sources.digests())

    sandbox_instance = _sandbox(tmp_path, fake_runsc, runtime_root)
    assert isinstance(sandbox_instance, gv.GVisorSandbox)


# -- a changed host contract file is refused, naming "contract" and both versions


def test_a_changed_host_contract_file_is_refused(
    tmp_path: Path, fake_runsc: Path, host_sources: _HostSources
) -> None:
    runtime_root = _provision_runtime_root(tmp_path / "runtime-root")
    _write_manifest(runtime_root, contract_version="0.1.0", **host_sources.digests())

    # The host's contract changed since the root was provisioned.
    (host_sources.contract_dir / "__init__.py").write_text('CONTRACT_VERSION = "0.3.0"\n', encoding="utf-8")

    with pytest.raises(gv.GVisorUnavailableError, match=gv.GVISOR_RUNTIME_STALE_CODE) as excinfo:
        _sandbox(tmp_path, fake_runsc, runtime_root)

    message = str(excinfo.value)
    assert "contract" in message
    assert "0.1.0" in message  # the manifest's own contract_version
    assert "0.2.0" in message  # this process's real, current contract.CONTRACT_VERSION
    assert "deploy/gvisor/provision_runtime.sh" in message
    assert "sudo" in message


# -- a changed child is refused, naming the child -----------------------------


def test_a_changed_host_child_bootstrap_is_refused(
    tmp_path: Path, fake_runsc: Path, host_sources: _HostSources
) -> None:
    runtime_root = _provision_runtime_root(tmp_path / "runtime-root")
    _write_manifest(runtime_root, **host_sources.digests())

    # The host's sandbox-child bootstrap changed since the root was provisioned.
    host_sources.child_path.write_bytes(host_sources.child_path.read_bytes() + b"\n# edited on the host\n")

    with pytest.raises(gv.GVisorUnavailableError, match=gv.GVISOR_RUNTIME_STALE_CODE) as excinfo:
        _sandbox(tmp_path, fake_runsc, runtime_root)

    assert "child" in str(excinfo.value)


def test_a_changed_host_app_file_is_refused(tmp_path: Path, fake_runsc: Path, host_sources: _HostSources) -> None:
    runtime_root = _provision_runtime_root(tmp_path / "runtime-root")
    _write_manifest(runtime_root, **host_sources.digests())

    # The host's app package changed since the root was provisioned.
    (host_sources.app_dir / "module_loader.py").write_text("# edited module loader\n", encoding="utf-8")

    with pytest.raises(gv.GVisorUnavailableError, match=gv.GVISOR_RUNTIME_STALE_CODE) as excinfo:
        _sandbox(tmp_path, fake_runsc, runtime_root)

    assert "app" in str(excinfo.value)


# -- a manifest without the new fields is refused, never passed silently -----


def test_a_manifest_without_the_staleness_fields_is_refused(
    tmp_path: Path, fake_runsc: Path, host_sources: _HostSources
) -> None:
    # The live 2026-10-06 shape: a manifest with tree_sha256 but none of the
    # fields this guard adds.
    runtime_root = _provision_runtime_root(tmp_path / "runtime-root")
    _write_manifest(runtime_root)  # every staleness field left _ABSENT

    with pytest.raises(gv.GVisorUnavailableError, match=gv.GVISOR_RUNTIME_STALE_CODE) as excinfo:
        _sandbox(tmp_path, fake_runsc, runtime_root)

    message = str(excinfo.value)
    assert "provisioned before the staleness guard" in message
    assert "re-provision" in message
    assert "deploy/gvisor/provision_runtime.sh" in message


def test_a_manifest_missing_just_one_staleness_field_is_refused(
    tmp_path: Path, fake_runsc: Path, host_sources: _HostSources
) -> None:
    runtime_root = _provision_runtime_root(tmp_path / "runtime-root")
    _write_manifest(runtime_root, **host_sources.digests())
    # Partially upgraded manifest: everything but contract_version.
    manifest_path = gv._manifest_path(runtime_root)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    del manifest["contract_version"]
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(gv.GVisorUnavailableError, match=gv.GVISOR_RUNTIME_STALE_CODE) as excinfo:
        _sandbox(tmp_path, fake_runsc, runtime_root)

    assert "contract_version" in str(excinfo.value)


# -- the tree_sha256 check is unchanged and still runs first ------------------


def test_tree_sha256_check_runs_before_the_staleness_check(
    tmp_path: Path, fake_runsc: Path, host_sources: _HostSources
) -> None:
    runtime_root = _provision_runtime_root(tmp_path / "runtime-root")
    manifest_path = _write_manifest(runtime_root, **host_sources.digests())
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["tree_sha256"] = "0" * 64  # wrong on purpose
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    # Also make the host contract stale, so if the staleness check somehow
    # ran first it would raise GVISOR_RUNTIME_STALE_CODE instead.
    (host_sources.contract_dir / "__init__.py").write_text('CONTRACT_VERSION = "9.9.9"\n', encoding="utf-8")

    with pytest.raises(gv.GVisorUnavailableError, match=gv.GVISOR_UNAVAILABLE_CODE) as excinfo:
        _sandbox(tmp_path, fake_runsc, runtime_root)
    assert gv.GVISOR_RUNTIME_STALE_CODE not in str(excinfo.value)


# -- _source_tree_sha256: the shared digest function itself -------------------


def test_source_tree_sha256_matches_hand_computed_digest(tmp_path: Path) -> None:
    root = tmp_path / "tiny-source"
    (root / "a").mkdir(parents=True)
    (root / "a" / "one.py").write_bytes(b"one")
    (root / "two.py").write_bytes(b"two")

    lines = [
        f"{hashlib.sha256(b'one').hexdigest()}  ./a/one.py\n",
        f"{hashlib.sha256(b'two').hexdigest()}  ./two.py\n",
    ]
    expected = hashlib.sha256("".join(lines).encode("utf-8")).hexdigest()
    assert gv._source_tree_sha256(root) == expected


def test_source_tree_sha256_matches_the_shell_pipeline(tmp_path: Path) -> None:
    root = tmp_path / "tiny-source"
    (root / "nested").mkdir(parents=True)
    (root / "nested" / "B.py").write_bytes(b"content-b")
    (root / "a.py").write_bytes(b"content-a")

    shell_digest = subprocess.run(
        "find . -type f -print0 | LC_ALL=C sort -z | xargs -0 sha256sum | sha256sum | cut -d' ' -f1",
        shell=True,
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    assert gv._source_tree_sha256(root) == shell_digest


def test_source_tree_sha256_is_independent_of_pycache(tmp_path: Path) -> None:
    root = tmp_path / "tiny-source"
    root.mkdir()
    (root / "mod.py").write_bytes(b"content")
    before = gv._source_tree_sha256(root)

    pycache = root / "__pycache__"
    pycache.mkdir()
    (pycache / "mod.cpython-312.pyc").write_bytes(b"bytecode, not source")
    nested_pycache = root / "pkg" / "__pycache__"
    nested_pycache.mkdir(parents=True)
    (nested_pycache / "other.cpython-312.pyc").write_bytes(b"more bytecode")

    assert gv._source_tree_sha256(root) == before


def test_source_tree_sha256_is_independent_of_mtime(tmp_path: Path) -> None:
    import os
    import time

    root = tmp_path / "tiny-source"
    root.mkdir()
    (root / "mod.py").write_bytes(b"content")
    before = gv._source_tree_sha256(root)

    os.utime(root / "mod.py", (time.time() + 1000, time.time() + 1000))
    assert gv._source_tree_sha256(root) == before


def test_source_tree_sha256_still_reacts_to_a_changed_file(tmp_path: Path) -> None:
    root = tmp_path / "tiny-source"
    root.mkdir()
    target = root / "mod.py"
    target.write_bytes(b"one")
    before = gv._source_tree_sha256(root)

    target.write_bytes(b"two")
    after = gv._source_tree_sha256(root)

    assert before != after
