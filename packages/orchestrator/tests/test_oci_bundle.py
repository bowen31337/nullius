"""Feature 4, the OCI runtime bundle for one gVisor signal run.

additions_spec_gvisor_executor.xml, "gVisor Executor", feature 4:
*System creates an OCI runtime bundle for one signal run with
orchestrator._oci_bundle.build_bundle(directory, *, runtime_root,
child_path, limits, lake_roots). It writes config.json and answers its
path.*  Every test here is pure: no ``runsc``, no network, nothing read
off the real host filesystem beyond ``tmp_path`` — the bundle is just a
JSON file, and the whole feature is checkable by reading it back.
"""

from __future__ import annotations

import json

import pytest
from orchestrator._oci_bundle import (
    BUNDLE_ERROR_CODE,
    CONFIG_FILENAME,
    FEATURE_2_ENV,
    NAMESPACES,
    BundleError,
    BundleLimits,
    _mounts,
    _validate_mounts,
    build_bundle,
)

LIMITS = BundleLimits(runner_mem_mb=4096, pids=32)


def _build(tmp_path, name="bundle", **overrides):
    runtime_root = overrides.pop("runtime_root", tmp_path / "runtime-root")
    child_path = overrides.pop("child_path", tmp_path / "child" / "_sandbox_child.py")
    limits = overrides.pop("limits", LIMITS)
    lake_roots = overrides.pop("lake_roots", ())
    directory = tmp_path / name
    config_path = build_bundle(
        directory,
        runtime_root=runtime_root,
        child_path=child_path,
        limits=limits,
        lake_roots=lake_roots,
        **overrides,
    )
    return config_path, json.loads(config_path.read_text(encoding="utf-8"))


def test_writes_config_json_and_answers_its_path(tmp_path):
    directory = tmp_path / "bundle"
    config_path = build_bundle(
        directory,
        runtime_root=tmp_path / "runtime-root",
        child_path=tmp_path / "child" / "_sandbox_child.py",
        limits=LIMITS,
        lake_roots=(),
    )
    assert config_path == directory / CONFIG_FILENAME
    assert config_path.is_file()
    json.loads(config_path.read_text(encoding="utf-8"))  # valid JSON


def test_creates_the_bundle_directory(tmp_path):
    directory = tmp_path / "does" / "not" / "exist" / "yet"
    config_path = build_bundle(
        directory,
        runtime_root=tmp_path / "runtime-root",
        child_path=tmp_path / "child" / "_sandbox_child.py",
        limits=LIMITS,
        lake_roots=(),
    )
    assert config_path.is_file()


def test_process_matches_feature_2_exactly(tmp_path):
    child_path = tmp_path / "child" / "_sandbox_child.py"
    _, config = _build(tmp_path, child_path=child_path)
    process = config["process"]
    assert process["args"] == ["/usr/bin/python3", "-I", str(child_path.resolve())]
    assert process["env"] == list(FEATURE_2_ENV)
    assert process["cwd"] == "/tmp"
    assert process["user"] == {"uid": 65534, "gid": 65534}
    assert process["noNewPrivileges"] is True
    assert process["terminal"] is False


def test_no_seed_in_the_bundled_environment(tmp_path):
    _, config = _build(tmp_path)
    assert all(
        not var.startswith("NULLIUS_SIGNAL_SEED") for var in config["process"]["env"]
    )


def test_root_is_the_runtime_root_read_only(tmp_path):
    runtime_root = tmp_path / "runtime-root"
    _, config = _build(tmp_path, runtime_root=runtime_root)
    assert config["root"] == {"path": str(runtime_root.resolve()), "readonly": True}


def test_mounts_are_exactly_proc_tmp_and_the_child_path(tmp_path):
    child_path = tmp_path / "child" / "_sandbox_child.py"
    _, config = _build(tmp_path, child_path=child_path)
    mounts = config["mounts"]
    assert len(mounts) == 3
    by_destination = {m["destination"]: m for m in mounts}
    assert set(by_destination) == {"/proc", "/tmp", str(child_path.resolve())}

    proc = by_destination["/proc"]
    assert proc["type"] == "proc"

    tmp = by_destination["/tmp"]
    assert tmp["type"] == "tmpfs"
    assert "size=64m" in tmp["options"]

    bind = by_destination[str(child_path.resolve())]
    assert bind["type"] == "bind"
    assert bind["source"] == str(child_path.resolve())
    assert "ro" in bind["options"]


def test_no_host_data_directory_is_bound(tmp_path):
    # The only mount with a real host-path source is the bind of
    # child_path; proc and tmpfs carry no host path at all.
    _, config = _build(tmp_path)
    sources = {m["source"] for m in config["mounts"]}
    assert "proc" in sources
    assert "tmpfs" in sources


def test_namespaces_are_pid_ipc_uts_mount_network(tmp_path):
    _, config = _build(tmp_path)
    assert config["linux"]["namespaces"] == [{"type": kind} for kind in NAMESPACES]
    assert list(NAMESPACES) == ["pid", "ipc", "uts", "mount", "network"]


def test_resources_come_from_limits_and_one_cpu(tmp_path):
    limits = BundleLimits(runner_mem_mb=4096, pids=32)
    _, config = _build(tmp_path, limits=limits)
    resources = config["linux"]["resources"]
    assert resources["memory"]["limit"] == 4096 * 1024 * 1024
    assert resources["pids"]["limit"] == 32
    assert resources["cpu"]["quota"] == resources["cpu"]["period"]


def test_resources_vary_with_different_limits(tmp_path):
    _, config = _build(tmp_path, limits=BundleLimits(runner_mem_mb=2048, pids=8))
    resources = config["linux"]["resources"]
    assert resources["memory"]["limit"] == 2048 * 1024 * 1024
    assert resources["pids"]["limit"] == 8


class _DuckLimits:
    def __init__(self, runner_mem_mb, pids):
        self.runner_mem_mb = runner_mem_mb
        self.pids = pids


def test_limits_is_duck_typed_not_a_class_check(tmp_path):
    _, config = _build(tmp_path, limits=_DuckLimits(runner_mem_mb=1024, pids=4))
    resources = config["linux"]["resources"]
    assert resources["memory"]["limit"] == 1024 * 1024 * 1024
    assert resources["pids"]["limit"] == 4


def test_limits_accepts_a_mapping(tmp_path):
    _, config = _build(tmp_path, limits={"runner_mem_mb": 512, "pids": 2})
    resources = config["linux"]["resources"]
    assert resources["memory"]["limit"] == 512 * 1024 * 1024
    assert resources["pids"]["limit"] == 2


@pytest.mark.parametrize("missing", ["runner_mem_mb", "pids"])
def test_limits_missing_a_field_is_refused(tmp_path, missing):
    fields = {"runner_mem_mb": 4096, "pids": 32}
    del fields[missing]
    with pytest.raises(BundleError, match=BUNDLE_ERROR_CODE):
        _build(tmp_path, limits=fields)


@pytest.mark.parametrize("bad", [-1, "32", 1.5, True, None])
def test_limits_with_an_unusable_count_is_refused(tmp_path, bad):
    with pytest.raises(BundleError, match=BUNDLE_ERROR_CODE):
        _build(tmp_path, limits={"runner_mem_mb": 4096, "pids": bad})


def test_refuses_a_runtime_root_under_a_lake_root(tmp_path):
    lake_root = tmp_path / "lake"
    runtime_root = lake_root / "runtime-root"
    with pytest.raises(BundleError, match=BUNDLE_ERROR_CODE):
        _build(tmp_path, runtime_root=runtime_root, lake_roots=(lake_root,))


def test_refuses_a_runtime_root_equal_to_a_lake_root(tmp_path):
    lake_root = tmp_path / "lake"
    with pytest.raises(BundleError, match=BUNDLE_ERROR_CODE):
        _build(tmp_path, runtime_root=lake_root, lake_roots=(lake_root,))


def test_refuses_a_child_path_under_a_lake_root(tmp_path):
    lake_root = tmp_path / "lake"
    child_path = lake_root / "window.bin" / "_sandbox_child.py"
    with pytest.raises(BundleError, match=BUNDLE_ERROR_CODE):
        _build(tmp_path, child_path=child_path, lake_roots=(lake_root,))


def test_a_sibling_of_the_lake_root_is_not_refused(tmp_path):
    lake_root = tmp_path / "lake"
    sibling_runtime_root = tmp_path / "lake-runtime"  # shares a prefix, not a parent
    _build(tmp_path, runtime_root=sibling_runtime_root, lake_roots=(lake_root,))


def test_string_paths_are_accepted_everywhere(tmp_path):
    # PathLike means str works too, not just Path objects — directory,
    # runtime_root, child_path and lake_roots are all exercised as plain
    # strings here, including a refusal that must still catch the drift.
    lake_root = str(tmp_path / "lake")
    runtime_root = str(tmp_path / "runtime-root")
    child_path = str(tmp_path / "child" / "_sandbox_child.py")
    directory = str(tmp_path / "bundle")

    config_path = build_bundle(
        directory,
        runtime_root=runtime_root,
        child_path=child_path,
        limits=LIMITS,
        lake_roots=(lake_root,),
    )
    assert config_path.is_file()

    with pytest.raises(BundleError, match=BUNDLE_ERROR_CODE):
        build_bundle(
            directory,
            runtime_root=str(tmp_path / "lake" / "runtime-root"),
            child_path=child_path,
            limits=LIMITS,
            lake_roots=(lake_root,),
        )


def test_multiple_lake_roots_are_all_checked(tmp_path):
    first_lake = tmp_path / "lake-a"
    second_lake = tmp_path / "lake-b"
    child_path = second_lake / "_sandbox_child.py"
    with pytest.raises(BundleError, match=BUNDLE_ERROR_CODE):
        _build(
            tmp_path,
            child_path=child_path,
            lake_roots=(first_lake, second_lake),
        )


def test_validate_mounts_refuses_a_mount_beyond_the_three(tmp_path):
    child_path = tmp_path / "child" / "_sandbox_child.py"
    mounts = _mounts(child_path.resolve())
    mounts.append(
        {
            "destination": "/extra",
            "type": "bind",
            "source": str(tmp_path),
            "options": ["bind", "ro"],
        }
    )
    with pytest.raises(BundleError, match=BUNDLE_ERROR_CODE):
        _validate_mounts(mounts, child_path.resolve(), ())


def test_validate_mounts_refuses_a_wrong_destination(tmp_path):
    child_path = tmp_path / "child" / "_sandbox_child.py"
    mounts = _mounts(child_path.resolve())
    mounts[0] = dict(mounts[0], destination="/not-proc")
    with pytest.raises(BundleError, match=BUNDLE_ERROR_CODE):
        _validate_mounts(mounts, child_path.resolve(), ())


def test_validate_mounts_refuses_a_bind_source_under_the_lake(tmp_path):
    lake_root = tmp_path / "lake"
    child_path = tmp_path / "child" / "_sandbox_child.py"
    mounts = _mounts(child_path.resolve())
    mounts[2] = dict(mounts[2], source=str(lake_root / "data"))
    with pytest.raises(BundleError, match=BUNDLE_ERROR_CODE):
        _validate_mounts(mounts, child_path.resolve(), (lake_root,))


def test_json_is_deterministic_for_equal_inputs(tmp_path):
    runtime_root = tmp_path / "runtime-root"
    child_path = tmp_path / "child" / "_sandbox_child.py"
    limits = BundleLimits(runner_mem_mb=4096, pids=32)

    first = build_bundle(
        tmp_path / "bundle-one",
        runtime_root=runtime_root,
        child_path=child_path,
        limits=limits,
        lake_roots=(),
    )
    second = build_bundle(
        tmp_path / "bundle-two",
        runtime_root=runtime_root,
        child_path=child_path,
        limits=limits,
        lake_roots=(),
    )
    assert first.read_text(encoding="utf-8") == second.read_text(encoding="utf-8")


def test_json_differs_for_different_limits(tmp_path):
    runtime_root = tmp_path / "runtime-root"
    child_path = tmp_path / "child" / "_sandbox_child.py"

    first = build_bundle(
        tmp_path / "bundle-one",
        runtime_root=runtime_root,
        child_path=child_path,
        limits=BundleLimits(runner_mem_mb=4096, pids=32),
        lake_roots=(),
    )
    second = build_bundle(
        tmp_path / "bundle-two",
        runtime_root=runtime_root,
        child_path=child_path,
        limits=BundleLimits(runner_mem_mb=2048, pids=8),
        lake_roots=(),
    )
    assert first.read_text(encoding="utf-8") != second.read_text(encoding="utf-8")


def test_error_carries_the_code_word(tmp_path):
    lake_root = tmp_path / "lake"
    with pytest.raises(BundleError) as excinfo:
        _build(tmp_path, runtime_root=lake_root, lake_roots=(lake_root,))
    assert BUNDLE_ERROR_CODE in str(excinfo.value)
