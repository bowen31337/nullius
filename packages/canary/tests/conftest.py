"""Suite-local fixtures for the canary package's tests.

This suite lives inside the workspace member (``packages/canary/tests``)
rather than the repository-level ``tests/`` tree, so the shared fixtures
in ``tests/conftest.py`` do not reach it — conftest scope follows
directories. Nor does this conftest reproduce the database isolation
those shared fixtures guarantee: feature 135 is an assertion, not a
persistence step, and the pin sweep writes nothing anywhere. The one
isolation that matters here is the environment — the member reads
``NULLIUS_EVALUATOR_IMAGE`` (the evaluator container's pin, which the
sweep resolves through the same spelling the evaluator service does),
so a developer shell that carries one would leak into every assertion
below.

The path bootstrap below puts the member's ``src/`` on ``sys.path`` —
the same mechanism the module loader uses when it scans members —
because the root project does not depend on this member and the venv
therefore does not install it; this suite runs with the repository's
pytest (``uv run --all-packages pytest packages/canary``).

The environment fixture is deliberately *explicit* rather than
autouse: the member's whole point is that it refuses to accept an
unpinned or tag-only container, so a suite that silently supplied a
pin would hide the refusal it exists to pin. Tests that want a swept
deployment ask for :func:`canary_env`, and the tests that assert the
refusal ask for nothing and get the bare environment.

The isolation also clears the device variables feature 140 reads
(``NULLIUS_EVAL_DEVICE`` and ``NULLIUS_REPLAY_DEVICE``): the device
sweep reads the process environment by default, so a developer shell
carrying one would leak into the tests that assert the CPU is the
passing case, and the "unset variable is the CPU" tests would depend
on the shell not having one. And it clears the allowlist variable
feature 139 reads (``NULLIUS_SEARCHED_IMPORTS``) for the same reason:
the allowlist resolution defaults when the variable is unset, so a
shell carrying one would silently change which ceiling the screen
tests judge under.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

#: A digest-pinned reference, spelled out rather than computed so the
#: tests that assert on it are readable. ``ab`` repeated 32 times is a
#: valid sha256 hex digest of the right width; nothing here needs it to
#: be a real image.
PINNED_EVALUATOR_IMAGE = "ghcr.io/nullius/evaluator@sha256:" + "ab" * 32
PINNED_EVALUATOR_DIGEST = "sha256:" + "ab" * 32

#: A second, different digest — the "the image moved" case of §15's
#: failure table, which is what a moved pin is the audit-side face of.
OTHER_PINNED_IMAGE = "ghcr.io/nullius/evaluator@sha256:" + "cd" * 32
OTHER_PINNED_DIGEST = "sha256:" + "cd" * 32

#: A second role's pinned reference — the sweep is over a *set*, and a
#: one-role declaration cannot show a refusal that names its siblings.
PINNED_RUNNER_IMAGE = "ghcr.io/nullius/runner@sha256:" + "ef" * 32


@pytest.fixture(autouse=True)
def _image_env_isolation(monkeypatch: pytest.MonkeyPatch) -> None:
    """Clear the canary's environment before every test.

    The member reads ``NULLIUS_EVALUATOR_IMAGE`` — the evaluator
    container's pin, the one entry :data:`canary.IMAGE_ENV_VARS`
    declares today — from the process, so a developer shell that
    carries one would leak into every assertion below. Clearing it
    makes each test state the environment it needs, and makes the
    "unset variable is refused" tests honest rather than dependent on
    the shell not having one.

    It also clears the two device variables feature 140 reads —
    ``NULLIUS_EVAL_DEVICE`` and ``NULLIUS_REPLAY_DEVICE`` — because the
    device sweep reads the process environment by default, so a
    developer shell carrying one would leak into the tests that assert
    the CPU is the passing case. And it clears the allowlist variable
    feature 139 reads — ``NULLIUS_SEARCHED_IMPORTS`` — because the
    allowlist resolution falls back to its default when the variable is
    unset, so a shell carrying one would silently change which ceiling
    the screen tests judge under.

    It clears ``PYTHONHASHSEED`` too, for feature 138: the order sweep
    reads the variable out of the process environment by default, so a
    developer shell (or a test runner started under one) carrying a
    non-zero seed would make every "the unset case is recorded, not
    refused" assertion fail for a reason that has nothing to do with the
    sweep. Clearing it here does *not* change the running interpreter's
    own hash-randomization flag — that was fixed before this conftest
    was imported, which is exactly why the sweep reads the declaration
    and the flag as two separate facts.

    And it clears the three variables feature 137 reads —
    ``OMP_NUM_THREADS``, ``MKL_NUM_THREADS`` and the library-level pool
    floor — for the strongest version of the same reason: a *thread cap*
    is read by the numerics at their own import, so a test runner started
    under one has already been summed single-threaded however the sweep
    is called. Clearing the variable here cannot undo that for this
    process (which is exactly the module's point, and why the sweep reads
    the declaration while ``interpreter_thread_pool`` reports the pool),
    but it does keep the *declaration* assertions honest: without it, a
    suite run under ``OMP_NUM_THREADS=16`` would refuse the
    single-threaded cases for a reason that has nothing to do with the
    test, and a suite run under the right value would pass the refusal
    cases vacuously. Tests that want a capped worker ask for
    :func:`capped_env` and get one.
    """
    for variable in (
        "NULLIUS_EVALUATOR_IMAGE",
        "NULLIUS_EVAL_DEVICE",
        "NULLIUS_REPLAY_DEVICE",
        "NULLIUS_SEARCHED_IMPORTS",
        "PYTHONHASHSEED",
        "OMP_NUM_THREADS",
        "MKL_NUM_THREADS",
        "POLARS_MAX_THREADS",
    ):
        monkeypatch.delenv(variable, raising=False)


@pytest.fixture
def canary_env(monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    """A complete, pinned canary environment.

    ``NULLIUS_EVALUATOR_IMAGE`` pinned to :data:`PINNED_EVALUATOR_IMAGE`.
    Returned as a mapping so a test can assert against the exact values
    it configured, and so a test can pass the same mapping to a service
    instead of relying on the process — the two spellings must agree,
    which is what the service's ``env`` parameter is for.
    """
    monkeypatch.setenv("NULLIUS_EVALUATOR_IMAGE", PINNED_EVALUATOR_IMAGE)
    return {"NULLIUS_EVALUATOR_IMAGE": PINNED_EVALUATOR_IMAGE}


#: The environment variable naming the relational store — the one spelling
#: every store in this workspace already uses, and the one feature 141's
#: reference store resolves.
DATABASE_URL_ENV = "DATABASE_URL"


@pytest.fixture
def test_database_url(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    """Point ``DATABASE_URL`` at a per-test SQLite file, and return the URL.

    The package suite cannot reach the root conftest's ``test_database_url`` —
    conftest scope follows directories — and feature 141's store is a
    persistence step that writes to the deployment's relational store, so the
    isolation the root conftest guarantees there must be restated here: every
    test that asks for this fixture gets its own throwaway SQLite file, and
    ``DATABASE_URL`` is set to it for the duration of the test. The URL is the
    one the code under test sees, so a composed store resolves to it.
    """
    url = f"sqlite:///{tmp_path / 'reference.db'}"
    monkeypatch.setenv(DATABASE_URL_ENV, url)
    return url


#: §12's cap values, spelled out rather than imported from the member, so a
#: test that asserts on them is readable and a drift in the member's constant
#: is a test failure rather than a silently-followed rename.
CAPPED_OMP = "1"
CAPPED_MKL = "1"


@pytest.fixture
def capped_env(monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    """A complete, single-threaded worker environment — feature 137.

    Both of §12's caps at the pin, in the process *and* returned as a mapping
    so a test can assert against exactly what it configured and can hand the
    same mapping to a sweep instead of relying on the shell — the two
    spellings must agree, which is what the sweep's ``env`` parameter is for.
    Deliberately *explicit* rather than autouse, matching :func:`canary_env`
    and for the same reason: the sweep's refusal is the feature, so a suite
    that silently capped every test would hide the refusal it exists to pin.
    """
    monkeypatch.setenv("OMP_NUM_THREADS", CAPPED_OMP)
    monkeypatch.setenv("MKL_NUM_THREADS", CAPPED_MKL)
    return {"OMP_NUM_THREADS": CAPPED_OMP, "MKL_NUM_THREADS": CAPPED_MKL}
