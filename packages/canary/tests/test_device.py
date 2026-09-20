"""No GPU in either path — feature 140.

These tests pin :mod:`canary._device` — the classifier that reads a
device declaration, the sweep that refuses a GPU in the eval path *and*
the replay path, and the refusals that keep it an *assertion* rather than
a summary. The properties under test are the ones the module docstring
argues:

* the refusal is over both paths — a GPU in either is refused, and an
  unset variable is the CPU, the contract's desired state;
* the sweep is a pure parser over strings a deployment already wrote,
  reading no environment at import and resolving nothing;
* the refusal is collective — one error names every path that declared a
  GPU, with the variable behind it and the value as written;
* a GPU is refused and an unrecognized device is refused too, but a CPU
  — or the absence of a declaration — is the passing case, recorded
  rather than raised;
* the verdict is a value; the refusal is the feature.

The device strings below are real declarations, not mocks: the point of
the feature is that a deployment satisfies the contract by running on the
CPU, so the passing cases use the CPU and the absence of a declaration,
and the failing cases use the GPU and the spellings a deployment might
reach for.
"""

from __future__ import annotations

import dataclasses

import pytest
from canary import (
    CPU,
    DEVICE_ENV_VARS,
    EVAL_PATH,
    GPU,
    REPLAY_PATH,
    CanaryDeviceError,
    CanaryError,
    CanaryImageError,
    CanaryService,
    DevicePaths,
    reject_gpus,
    reject_gpus_from_env,
)
from canary._device import classify_device

# -- The classifier: a device string to CPU or GPU ----------------------------


@pytest.mark.parametrize(
    "value",
    ["cpu", "CPU", " cpu ", "Cpu", "cPu"],
    ids=["cpu", "upper", "padded", "title", "mixed"],
)
def test_a_cpu_declaration_classifies_as_the_cpu(value: str) -> None:
    # The contract's desired state, spelled several ways. Whitespace is
    # stripped and the value lower-cased, so all of these are the CPU.
    assert classify_device(value) == CPU


@pytest.mark.parametrize(
    "value",
    [
        "gpu",
        "GPU",
        "cuda",
        "cuda:0",
        "cuda:3",
        "cuda:15",
        "nvidia",
        "xpu",
        "rocm",
    ],
    ids=["gpu", "upper", "cuda", "cuda:0", "cuda:3", "cuda:15", "nvidia", "xpu", "rocm"],
)
def test_a_gpu_declaration_classifies_as_the_gpu(value: str) -> None:
    # Every spelling a deployment might reach for — the vendor-neutral
    # ``gpu``, the CUDA runtime (bare and indexed), the vendor name, the
    # oneAPI and ROCm stacks — is the GPU, refused for the same reason: a
    # GPU kernel's reduction order is fixed by its block and grid shape
    # rather than by the input, so two runs of one seeded signal can
    # diverge in float.
    assert classify_device(value) == GPU


@pytest.mark.parametrize(
    "value",
    ["cuda:", "cuda:x", "cuda:-1", "tpu", "fpga", "accelerator", "cpu:0"],
    ids=["cuda-empty-index", "cuda-bad-index", "cuda-negative", "tpu", "fpga", "name", "cpu-indexed"],
)
def test_an_unrecognized_device_is_refused(value: str) -> None:
    # A declaration the sweep cannot place is a device the determinism
    # contract cannot vouch for, and accepting it would be letting a GPU
    # onto the path under a spelling the sweep did not think to forbid.
    # A malformed ``cuda:`` is refused rather than silently accepted, so
    # a typo cannot smuggle a GPU past the refusal.
    with pytest.raises(CanaryDeviceError, match="names no device"):
        classify_device(value)


@pytest.mark.parametrize("value", ["", "   ", None, 5, 1.0, True, ["gpu"]], ids=["empty", "blank", "none", "int", "float", "bool", "list"])
def test_a_non_declaration_is_refused(value: object) -> None:
    # The device is a string a deployment wrote; a value that is not a
    # non-empty string is a broken declaration rather than a device.
    with pytest.raises(CanaryDeviceError, match="non-empty string"):
        classify_device(value)


# -- The sweep's verb: both paths, GPU refused, empty accepted ------------------


def test_a_clean_environment_is_the_cpu_on_both_paths() -> None:
    # The contract's desired state, reached by declaring nothing: an unset
    # variable is the CPU, recorded rather than refused. The sweep is never
    # vacuous — it always checks the same two fixed paths and asserts
    # neither names a GPU.
    paths = reject_gpus_from_env({})
    assert isinstance(paths, DevicePaths)
    assert paths.kinds == {EVAL_PATH: CPU, REPLAY_PATH: CPU}
    assert paths.paths == (EVAL_PATH, REPLAY_PATH)


def test_an_explicit_cpu_declaration_is_recorded() -> None:
    # A CPU declaration is accepted and recorded — the sweep is not a pin
    # that must be present, it is a refusal of the GPU.
    paths = reject_gpus({"eval": "cpu", "replay": "cpu"})
    assert paths.kinds == {EVAL_PATH: CPU, REPLAY_PATH: CPU}


def test_a_blank_declaration_is_the_cpu() -> None:
    # Unset or blank: the path declares no device, which is the CPU.
    paths = reject_gpus({"eval": "", "replay": "   "})
    assert paths.kinds == {EVAL_PATH: CPU, REPLAY_PATH: CPU}


def test_a_gpu_in_the_eval_path_is_refused() -> None:
    with pytest.raises(CanaryDeviceError) as raised:
        reject_gpus_from_env({"NULLIUS_EVAL_DEVICE": "gpu"})
    assert "the eval path" in str(raised.value)
    assert "NULLIUS_EVAL_DEVICE" in str(raised.value)
    assert "GPU" in str(raised.value)


def test_a_gpu_in_the_replay_path_is_refused() -> None:
    # The correction the determinism contract's prerequisites apply: the
    # prohibition reaches the replay path too, a separate deployment that
    # reads materialized floats. A GPU there breaks the same guarantee.
    with pytest.raises(CanaryDeviceError) as raised:
        reject_gpus_from_env({"NULLIUS_REPLAY_DEVICE": "cuda:0"})
    assert "the replay path" in str(raised.value)
    assert "NULLIUS_REPLAY_DEVICE" in str(raised.value)


def test_a_gpu_in_either_path_is_refused_collectively() -> None:
    # One error names every path that declared a GPU, in sorted path order,
    # with the variable behind it and the value as written — a sweep that
    # stopped at the first would be re-run to learn the rest.
    with pytest.raises(CanaryDeviceError) as raised:
        reject_gpus_from_env(
            {"NULLIUS_EVAL_DEVICE": "gpu", "NULLIUS_REPLAY_DEVICE": "cuda:0"}
        )
    message = str(raised.value)
    assert "2 of 2 declared refused" in message
    assert "the eval path" in message
    assert "the replay path" in message
    # The eval path is named before the replay path — sorted order, stable.
    assert message.index("the eval path") < message.index("the replay path")


def test_an_unrecognized_device_is_refused_naming_the_value() -> None:
    with pytest.raises(CanaryDeviceError) as raised:
        reject_gpus_from_env({"NULLIUS_EVAL_DEVICE": "tpu"})
    assert "tpu" in str(raised.value)
    assert "names no device" in str(raised.value)


def test_a_clean_path_beside_a_gpu_path_is_still_refused() -> None:
    # The sweep is all-or-nothing: a GPU in one path refuses the whole
    # declaration, so a caller can never hold a partial sweep dressed as a
    # passed one.
    with pytest.raises(CanaryDeviceError):
        reject_gpus_from_env({"NULLIUS_EVAL_DEVICE": "cpu", "NULLIUS_REPLAY_DEVICE": "gpu"})


def test_the_refusal_names_the_value_as_written() -> None:
    # The value the operator wrote survives in the message, so the refusal
    # points at exactly what to change.
    with pytest.raises(CanaryDeviceError) as raised:
        reject_gpus({"eval": "CUDA:2"})
    assert "CUDA:2" in str(raised.value)


# -- The verdict record --------------------------------------------------------


def test_a_clean_sweep_records_what_it_checked() -> None:
    # The passing case is a value, not a bare "did not raise": the audit
    # that the GPU path was never taken is worth carrying, because §12's
    # whole point is that non-determinism does not announce itself.
    paths = reject_gpus_from_env({"NULLIUS_EVAL_DEVICE": "cpu"})
    assert paths.kinds[EVAL_PATH] == CPU
    assert paths.kinds[REPLAY_PATH] == CPU


def test_the_verdict_is_frozen() -> None:
    paths = reject_gpus_from_env({})
    with pytest.raises(dataclasses.FrozenInstanceError):
        paths.devices = ((EVAL_PATH, CPU),)  # type: ignore[misc]


def test_a_clean_verdict_cannot_carry_a_gpu() -> None:
    # A DevicePaths is the clean verdict, built only after every GPU is
    # refused, so a record that carried a GPU would say 'GPU-free' while
    # naming a GPU — the shape of an audit nobody can act on.
    with pytest.raises(CanaryDeviceError, match="the CPU"):
        DevicePaths(((EVAL_PATH, GPU), (REPLAY_PATH, CPU)))


def test_an_empty_verdict_is_refused() -> None:
    # The sweep always checks both paths; a verdict over an empty set of
    # paths checked nothing, which is the one reading the nightly canary
    # must never allow.
    with pytest.raises(CanaryDeviceError, match="records no paths"):
        DevicePaths(())


def test_a_duplicated_path_is_refused() -> None:
    with pytest.raises(CanaryDeviceError, match="swept twice"):
        DevicePaths(((EVAL_PATH, CPU), (EVAL_PATH, CPU)))


def test_the_verdict_sorts_its_paths() -> None:
    # Given out of order, the record normalizes to sorted path order, so
    # two sweeps cannot disagree about the order of their record.
    paths = DevicePaths(((REPLAY_PATH, CPU), (EVAL_PATH, CPU)))
    assert paths.paths == (EVAL_PATH, REPLAY_PATH)


# -- The explicit declaration ---------------------------------------------------


def test_the_explicit_declaration_is_swept_at_the_call_site() -> None:
    # A GPU handed in directly fails at the call site that made the
    # mistake, not on first use — the explicit form is for a test or a
    # caller that holds the device values rather than the environment.
    with pytest.raises(CanaryDeviceError, match="the eval path"):
        reject_gpus({"eval": "gpu"})


def test_the_explicit_declaration_reads_through_the_same_classifier() -> None:
    # One answer to "is this path GPU-free?": the explicit and environment
    # spellings funnel through the same sweep, so the two can never
    # disagree about what "the CPU" means.
    assert reject_gpus({"eval": "cpu", "replay": "cpu"}) == reject_gpus_from_env(
        {"NULLIUS_EVAL_DEVICE": "cpu", "NULLIUS_REPLAY_DEVICE": "cpu"}
    )


def test_the_explicit_declaration_refuses_a_non_mapping() -> None:
    with pytest.raises(CanaryDeviceError, match="a mapping"):
        reject_gpus(["gpu"])  # type: ignore[arg-type]


def test_the_explicit_declaration_refuses_a_malformed_path() -> None:
    with pytest.raises(CanaryDeviceError, match="non-empty string"):
        reject_gpus({"": "cpu"})


# -- The environment seam -------------------------------------------------------


def test_the_env_mapping_is_the_single_seam() -> None:
    # A service handed an explicit mapping resolves through it alone, with
    # no process values to fall through to.
    with pytest.raises(CanaryDeviceError):
        reject_gpus_from_env({"NULLIUS_EVAL_DEVICE": "gpu"})
    assert reject_gpus_from_env({}).kinds == {EVAL_PATH: CPU, REPLAY_PATH: CPU}


def test_the_process_environment_is_read_when_env_is_none() -> None:
    # The default spelling: no mapping handed in, the process environment
    # is read. A developer shell carrying a GPU variable would therefore
    # be caught — which is why the autouse fixture below clears it.
    paths = reject_gpus_from_env()
    assert paths.kinds == {EVAL_PATH: CPU, REPLAY_PATH: CPU}


def test_the_device_table_names_both_paths() -> None:
    # The sweep reads exactly this table — a path that is not declared here
    # is a path the sweep would silently let onto the GPU. Both paths are
    # named, because the feature's word is *and*.
    assert DEVICE_ENV_VARS == {
        EVAL_PATH: "NULLIUS_EVAL_DEVICE",
        REPLAY_PATH: "NULLIUS_REPLAY_DEVICE",
    }


# -- The taxonomy --------------------------------------------------------------


def test_the_device_refusal_is_a_canary_error_but_not_an_image_error() -> None:
    # A deployment can be perfectly pinned and still run on a GPU, and the
    # repairs differ (re-pin an image vs remove the GPU and run on the
    # CPU), so a caller must be able to tell them apart.
    assert issubclass(CanaryDeviceError, CanaryError)
    assert not issubclass(CanaryDeviceError, CanaryImageError)
    assert not issubclass(CanaryImageError, CanaryDeviceError)


# -- The composed component carries the refusal -------------------------------


def test_the_composed_service_exposes_the_device_sweep_beside_the_pin_sweep(
    canary_env: dict[str, str],
) -> None:
    # Feature 140 through the composed component: one value carries the
    # whole category's assertions, so a caller holding the composed canary
    # reaches the device refusal without importing submodules by name.
    service = CanaryService(env=canary_env)
    assert isinstance(service.devices, DevicePaths)
    assert service.devices.kinds == {EVAL_PATH: CPU, REPLAY_PATH: CPU}
    # ... and the pin sweep is still its own verb, unchanged.
    assert service.containers["evaluator"].digest == "sha256:" + "ab" * 32


def test_the_device_sweep_is_lazy_like_the_pin_sweep() -> None:
    # The factory builds this component on every create_app(), so the
    # device sweep must not fail composition on a deployment's device
    # configuration. A bare service constructs, and the refusal lands on
    # first use — here with no GPU declared, so it is the CPU.
    service = CanaryService()
    assert service._devices is None
    assert service.devices.kinds == {EVAL_PATH: CPU, REPLAY_PATH: CPU}
    # Resolved once: a deployment that re-read its device state mid-run
    # could observe two different truths about the same night.
    assert service.devices is service.devices


def test_the_device_sweep_refuses_a_gpu_on_first_use(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The refusal names the deployment's own misconfiguration, not a
    # composition fault — the surface a nightly runner would actually hold.
    monkeypatch.setenv("NULLIUS_EVAL_DEVICE", "gpu")
    service = CanaryService()
    with pytest.raises(CanaryDeviceError, match="the eval path"):
        _ = service.devices


def test_the_check_does_not_require_a_pinned_deployment() -> None:
    # Deliberately unlike ``containers``: a deployment whose pins are unset
    # is still perfectly able to learn that its paths are GPU-free. The two
    # are different failures with different repairs, and a caller must not
    # have to fix one to see the other.
    service = CanaryService(env={})
    assert service.devices.kinds == {EVAL_PATH: CPU, REPLAY_PATH: CPU}
