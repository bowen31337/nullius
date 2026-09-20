"""No GPU in either path — the device refusal.

app_spec.xml feature 140 (this category's, in "Determinism Guarantees &
Nightly Canary"): *"System rejects any GPU device in the evaluation path
and in the replay path, because float reproducibility requires a fixed
reduction order."* It is §12's "Float reproducibility | Fixed reduction
order; no ``fastmath``; no GPU in the eval path" row made into something a
run can *fail*, and the row the prerequisites open with — "No GPU anywhere;
GPU is prohibited in both the evaluation and replay paths by the
determinism contract" — with the correction §12.1 applies, that the
prohibition reaches the replay path too and not the eval path alone.

This module is that prohibition, read off the environment and asserted. It
is the fourth assertion the category layers onto the pin feature 135 keeps —
the lockfile, the thread caps, the hash-seed, the import allowlist and this
one, each reading the same frozen container from the same sweep — and it
follows the shape the others established: a pure parser over strings a
deployment already wrote, stdlib-only and import-cheap, so importing this
member on every factory scan (and on the replay path §1 keeps away from
anything that could perturb it) still costs composition nothing.

Four decisions carry the feature, and each is a reading of one word in it.

**The refusal is over both paths, and that is the point.** The feature's own
word is *and*: the evaluation path *and* the replay path. They are not the
same process — the replay is a separate deployment (§13, "Separate
deployment, separate operational profile"), and a GPU admitted to either
breaks the same guarantee, because the guarantee is about the *score*, and
the score is computed in whichever path computes it. So the sweep is over a
fixed table of two paths — :data:`EVAL_PATH` and :data:`REPLAY_PATH`, each
read from its own variable in :data:`DEVICE_ENV_VARS` — and a GPU in either
is refused. The two variables are spelled out rather than inferred, for the
same reason :data:`~canary.IMAGE_ENV_VARS` names its roles explicitly: a
device variable that is not read here is a GPU the sweep would silently
ignore, and a silently-ignored GPU is exactly the one that breaks the
replay.

**A GPU is refused; a CPU is the absence of a refusal, not a thing to pin.**
This is where the device sweep differs from the image sweep, and the
difference is load-bearing. The image sweep refuses an *empty* declaration —
a sweep over zero containers is green because it checked nothing, and vacuous
green is the one reading the nightly canary must never allow. The device
sweep does the opposite: an unset device variable is the *passing* case. The
determinism contract is "no GPU", and a deployment satisfies it by running on
the CPU, which is the default a deployment reaches by declaring nothing at
all. So a path whose variable is unset or blank is read as the CPU — not
skipped, but positively classified as the device the contract wants — and the
sweep is never vacuous because it always checks the same two fixed paths and
asserts neither names a GPU. A CPU declaration (``cpu``, explicitly) is
accepted and recorded; a GPU declaration (``gpu``, ``cuda``, ``cuda:0`` ...)
is refused; and a declaration the sweep cannot place — a string that is
neither — is refused too, naming the value, because an unrecognizable device
is a device the contract cannot vouch for, and accepting it would be
accepting a GPU wearing a spelling the sweep did not think to forbid.

**The refusal is collective and complete.** Exactly as the image sweep names
*every* unpinned container in one :class:`~canary.CanaryImageError`, this
sweep names *every* path that declares a GPU in one
:class:`~canary.CanaryDeviceError`: the eval path and the replay path, each
with the variable behind it and the value as written. A sweep that stopped at
the first would be re-run to learn the rest, and the operator of a nightly
assertion reads the whole deployment's device state in one message. The two
paths are checked in sorted order so the message is stable.

**The verdict is a value; the refusal is the feature.** On a healthy,
CPU-only deployment :func:`reject_gpus_from_env` returns a
:class:`DevicePaths` — the two paths, each classified as the CPU, recorded so
a nightly report can show *what it checked and that it was clean* rather than
merely that it did not raise. A record that a path was swept and found to be
the CPU is the audit the determinism contract asks for: §12's whole point is
that non-determinism "does not announce itself", so the proof that the GPU
path was never taken is worth carrying. The refusal, when a GPU is present,
is raised rather than returned — a GPU in the eval or replay path is a stop,
the deployment's own misconfiguration, and the caller that most needs it (a
nightly runner's entrypoint, a health check, the moment before dreaming is
allowed to continue) wants the exception, not a boolean it might forget to
check.

What this module deliberately does **not** do is *enforce* the CPU — it does
not set ``CUDA_VISIBLE_DEVICES``, pin a library, or launch a process. It is an
assertion, not a runtime, exactly as feature 135 is: it reads a string a
deployment already wrote and refuses it if it names a GPU. The enforcement —
actually keeping the GPU off the path — is the deployment's, in the
environment and the container the image sweep pins; this module is the check
that the deployment told the truth about it. It also does not resolve a
device or consult a driver: there is nothing to resolve, only a declaration
to read, and a declaration that names a GPU is refused rather than
second-guessed against whatever hardware happens to be present, because the
contract is about what the path is *configured* to run on, not what the
machine could be coerced into.

**The layering note.** Stdlib only — ``re``, a dataclass and a loop — with no
polars, no pyarrow, no lake, no environment and no numerics, for the reason
the whole category states: this package is imported on every factory scan and
on the replay path §1 keeps free of moving parts, and the device refusal must
not be the member that made that path expensive. It is carried by
:class:`~canary.CanaryService` at ``service.devices``, beside the pin sweep at
``service.containers`` — the same seam, the same laziness (resolved on first
use, so composition never fails on a deployment's device configuration), so a
caller holding the composed canary reaches the refusal without importing this
member's submodules by name.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Optional

from ._errors import CanaryDeviceError

__all__ = [
    "CPU",
    "DEVICE_ENV_VARS",
    "EVAL_PATH",
    "GPU",
    "REPLAY_PATH",
    "DevicePaths",
    "reject_gpus",
    "reject_gpus_from_env",
]

#: The path the dreaming evaluation runs in — the container the policy's
#: scores are computed in, and the one :data:`~canary.IMAGE_ENV_VARS` pins.
#: The feature's "evaluation path"; kept as a named constant so the sweep,
#: the service and the tests share one spelling of it.
EVAL_PATH = "eval"

#: The path the nightly canary replay runs in — a separate deployment (§13)
#: that reads materialized floats and calls no inference, and is therefore
#: held to the same no-GPU contract. The feature's "replay path", the half
#: the determinism contract's prerequisites were corrected to name (§12.1).
REPLAY_PATH = "replay"

#: The only device this system runs on. A declaration that names it is
#: accepted and recorded; a declaration that omits it (an unset variable) is
#: read as it too. Kept as a constant because it is the value a clean
#: :class:`DevicePaths` records for every path it checked.
CPU = "cpu"

#: The device this system refuses. Never returned by :func:`classify_device`;
#: a declaration that names it is the refusal, not a value the sweep carries.
GPU = "gpu"

#: The declared device for each path: path → the environment variable naming
#: that path's device. The sweep reads exactly this table — a path that is
#: not declared here is a path the sweep would silently let onto the GPU, and
#: a variable that is not read here is a GPU the contract would never catch.
#: Both paths are named, because the feature's word is *and*: a GPU in either
#: the evaluation path or the replay path breaks the same guarantee.
DEVICE_ENV_VARS: Mapping[str, str] = {
    EVAL_PATH: "NULLIUS_EVAL_DEVICE",
    REPLAY_PATH: "NULLIUS_REPLAY_DEVICE",
}

#: Tokens that name the CPU outright. Whitespace is stripped and the value
#: lower-cased before the comparison, so ``" CPU "``, ``"Cpu"`` and ``"cpu"``
#: are the same declaration. The CPU carries no index — there is one reduction
#: order to fix, and it is the single core's.
_CPU_TOKENS = frozenset({CPU})

#: Tokens that name a GPU outright, before the indexed forms. Each is a
#: spelling a deployment might reach for — the vendor-neutral ``gpu``, the
#: CUDA runtime, the vendor name, the oneAPI and ROCm stacks — and each is
#: refused for the same reason: a GPU kernel's reduction order depends on its
#: block and grid shape rather than on the input, so two runs of one seeded
#: signal over the same bytes can sum in a different order and diverge in
#: float, which is the divergence §12 calls invisible and the ``1e-12`` canary
#: exists to catch.
_GPU_TOKENS = frozenset({"gpu", "cuda", "nvidia", "xpu", "rocm"})

#: The indexed CUDA form — ``cuda:0``, ``cuda:1`` ... — a device name plus a
#: non-negative integer index. Anchored so a bare ``cuda`` falls through to
#: the token set and a malformed ``cuda:`` or ``cuda:x`` is refused as
#: unrecognized rather than silently accepted.
_CUDA_INDEXED_RE = re.compile(r"^cuda:\d+$")


def classify_device(value: object) -> str:
    """The device a declaration names — :data:`CPU` or :data:`GPU`.

    The one place a device string is read, so the refusal path and the
    recording path cannot disagree about what a value classifies as. The value
    is stripped and lower-cased, then placed: a CPU token is the CPU, a GPU
    token or an indexed CUDA form is the GPU, and anything else is a
    :class:`~canary.CanaryDeviceError` naming the value — because a declaration
    the sweep cannot place is a device the determinism contract cannot vouch
    for, and accepting it would be letting a GPU onto the path under a spelling
    the sweep did not think to forbid. A non-string is refused the same way:
    the device is a string a deployment wrote, and a value that is not one is
    a broken declaration rather than a device.
    """
    if not isinstance(value, str) or not value.strip():
        raise CanaryDeviceError(
            f"a device declaration must be a non-empty string, got "
            f"{value!r}; the eval and replay paths each run on the CPU, so a "
            "device declaration names the CPU, or names no device at all — "
            "and a value that is neither is a declaration the determinism "
            "contract cannot vouch for"
        )
    text = value.strip().lower()
    if text in _CPU_TOKENS:
        return CPU
    if text in _GPU_TOKENS or _CUDA_INDEXED_RE.match(text):
        return GPU
    raise CanaryDeviceError(
        f"a device declaration of {value!r} names no device this system "
        "recognizes: this system runs on the CPU only, so a declaration must "
        "name the CPU or name no device at all, and a string that is neither "
        "the CPU nor a GPU the sweep forbids is a device the determinism "
        "contract cannot vouch for"
    )


@dataclass(frozen=True)
class DevicePaths:
    """The eval and replay paths, swept and found GPU-free — the clean verdict.

    Feature 140's passing case, as a value: the paths the sweep checked, each
    recorded with the device it was classified as. Frozen and ordered, so a
    nightly report can file one record per deployment and compare it across
    nights. A :class:`DevicePaths` only ever exists when *every* path is the
    CPU — a GPU is refused before this value is built — so every recorded kind
    is :data:`CPU`, and the value is the audit that the GPU path was never
    taken: not a bare "did not raise", but *what was checked and that it was
    clean*, which is the proof §12's "non-determinism does not announce
    itself" asks for.
    """

    #: The checked paths, each as ``(path, device)``, sorted by path. Every
    #: device is :data:`CPU`, because a GPU never reaches a built value.
    devices: tuple[tuple[str, str], ...]

    def __post_init__(self) -> None:
        # A clean verdict is a statement about paths some sweep actually
        # checked, so every entry is validated before the value exists. The
        # alternative — trusting the constructor — is a record that could say
        # "GPU-free" while carrying a GPU, which is precisely the shape of an
        # audit nobody can act on.
        devices = tuple(self.devices)
        if not devices:
            raise CanaryDeviceError(
                "a device sweep records no paths: the sweep always checks the "
                "eval path and the replay path, and a verdict over an empty "
                "set of paths checked nothing — which is the one reading the "
                "nightly determinism canary must never allow (architecture "
                "§12)"
            )
        seen: set[str] = set()
        for path, device in devices:
            if not isinstance(path, str) or not path.strip():
                raise CanaryDeviceError(
                    f"a device sweep records a path of {path!r}: a path is the "
                    "word the refusal names, so a path that cannot be named "
                    "cannot be swept"
                )
            if path in seen:
                raise CanaryDeviceError(
                    f"the {path} path is swept twice: a path with two verdicts "
                    "is one path wearing two words, and the sweep could not say "
                    "which device the path ran on"
                )
            seen.add(path)
            if device != CPU:
                raise CanaryDeviceError(
                    f"a device sweep records the {path} path as {device!r}: a "
                    "DevicePaths is the clean verdict, built only after every "
                    "GPU is refused, so a path it carries is the CPU — and a "
                    "record that carried a GPU would say 'GPU-free' while "
                    "naming a GPU"
                )
        object.__setattr__(self, "devices", tuple(sorted(devices, key=lambda item: item[0])))

    @property
    def paths(self) -> tuple[str, ...]:
        """The checked paths, in sorted order."""
        return tuple(path for path, _ in self.devices)

    @property
    def kinds(self) -> dict[str, str]:
        """Path → device — the view a report files, always all-CPU."""
        return {path: device for path, device in self.devices}

    def __repr__(self) -> str:  # pragma: no cover - cosmetic
        return f"DevicePaths(paths={self.paths!r})"


def _sweep(
    entries: Mapping[str, str],
) -> DevicePaths:
    """Classify every path's device value, refuse completely.

    The one place the feature's *and* is enforced mechanically: both paths are
    checked, no GPU is dropped, and the refusal raised carries all of them in
    sorted path order. A path whose variable is unset or blank is the CPU —
    the contract's desired state, reached by declaring nothing — so it is
    recorded as the CPU rather than refused; a path whose value names a GPU is
    a refusal; and a value the classifier cannot place is a refusal naming the
    value. The refusal, when any path fails, is one
    :class:`~canary.CanaryDeviceError` over every failing path. ``entries`` is
    ``path → value`` (the value already read out of the environment or the
    explicit declaration); the variable behind each path is looked up in
    :data:`DEVICE_ENV_VARS` so the refusal can name it.
    """
    failures: list[str] = []
    devices: list[tuple[str, str]] = []
    for path, raw in sorted(entries.items(), key=lambda entry: entry[0]):
        variable = DEVICE_ENV_VARS.get(path)
        prefix = (
            f"{variable} (the {path} path)"
            if variable is not None
            else f"the {path} path"
        )
        blank = isinstance(raw, str) and not raw.strip()
        if blank:
            # Unset or blank: the path declares no device, which is the CPU —
            # the determinism contract's desired state, reached by naming
            # nothing. Recorded as the CPU so the verdict shows the path was
            # checked, not skipped.
            devices.append((path, CPU))
            continue
        try:
            device = classify_device(raw)
        except CanaryDeviceError as refusal:
            failures.append(f"{prefix}: {refusal}")
            continue
        if device == GPU:
            failures.append(
                f"{prefix}: declares a GPU device ({raw!r} classifies as the "
                "GPU): float reproducibility requires a fixed reduction order "
                "on a single CPU core, and a GPU kernel sums in an order fixed "
                "by its block and grid shape rather than by the input, so two "
                "runs of one seeded signal can diverge in float — the "
                "divergence architecture §12 names ('no GPU in the eval path') "
                "and the nightly canary exists to catch. Remove the GPU from "
                "this path and run on the CPU"
            )
            continue
        devices.append((path, device))
    if failures:
        raise CanaryDeviceError(
            "a GPU (or an unrecognized device) is declared in the eval or "
            f"replay path — {len(failures)} of {len(failures) + len(devices)} "
            "declared refused:\n  " + "\n  ".join(failures)
        )
    return DevicePaths(tuple(devices))


def reject_gpus(references: Mapping[str, str]) -> DevicePaths:
    """Refuse a GPU in an explicit declaration of paths: path → device value.

    Every entry is classified by :func:`classify_device`; every failure is
    collected; one :class:`~canary.CanaryDeviceError` names them all (see the
    module docstring for why the refusal is complete rather than first-wins).
    A path that declares no device (a blank value) is the CPU. Returns the
    :class:`DevicePaths` — all-or-nothing, so a caller can never hold a partial
    sweep dressed as a passed one. The explicit-declaration form, for a test or
    a caller that holds the device values directly rather than through the
    environment; :func:`reject_gpus_from_env` is the environment spelling.
    """
    if not isinstance(references, Mapping):
        raise CanaryDeviceError(
            "a device declaration must be a mapping of path to device value, "
            f"got {type(references).__name__}; the sweep reads one declaration "
            "per path, not a sequence of maybe-related strings"
        )
    for path in references:
        if not isinstance(path, str) or not path.strip():
            raise CanaryDeviceError(
                f"a device declaration's path must be a non-empty string, got "
                f"{path!r}; the path is the word the refusal names, so a path "
                "that cannot be named cannot be swept"
            )
    return _sweep({path: references[path] for path in references})


def reject_gpus_from_env(env: Optional[Mapping[str, str]] = None) -> DevicePaths:
    """Refuse a GPU in the eval and replay paths, read from an environment.

    Reads each path's variable from :data:`DEVICE_ENV_VARS` out of ``env`` —
    the same mapping seam the pin sweep resolves through, so a test or an
    operator can hand the refusal an environment without touching the process —
    or the process environment when ``env`` is ``None``. A variable that is
    unset or blank is the CPU (the contract's desired state); a variable that
    names a GPU is refused, naming the path, the variable and the value; and a
    value the sweep cannot place is refused naming the value. The
    composition-spelling counterpart of the explicit :func:`reject_gpus`: the
    service resolves its :attr:`~canary.CanaryService.devices` through here, so
    a deployment's device state is swept the same way whether a caller reaches
    it through the composed component or by hand.
    """
    source: Mapping[str, str] = {} if env is None else env
    return _sweep(
        {path: (source.get(variable) or "") for path, variable in DEVICE_ENV_VARS.items()}
    )
