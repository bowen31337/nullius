"""Import wiring and isolation for the nulloracle integration suite.

This suite lives under the repository-level ``tests/`` tree — alongside the
feature-store integration suite — because its subject is the *assembled*
system: the sidecar persisted through the app namespace, resolved from the
environment the shared fixtures provide, and reachable the way a later
feature in this category (``POST /target``, the campaign assignment, the KS
guard) will reach it.

Workspace members are not installed into the root environment — only the
root project and its dev group are — and the application factory imports
member packages by file path during its scan.  So this conftest puts the
member's ``src/`` tree on ``sys.path`` itself, the way
``tests/feature-store/conftest.py`` does, and the root conftest's lake and
database isolation applies as it does to every suite here.

The one guarantee this suite adds to the root conftest's: ``NULL_SIDECAR_PATH``
and ``NULL_SIDECAR_KEY_REF`` are cleared per test and never left pointing at
a deployment's real sidecar.  §7.1's file holds the null labels; a test that
wrote one into a real ``/z0/null/`` would be the exact accident this whole
member exists to make impossible.
"""

from __future__ import annotations

import sys
import uuid
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
MEMBER_SRC = REPO_ROOT / "packages" / "nulloracle" / "src"
FACTORY_SRC = REPO_ROOT / "src"

for _entry in (str(MEMBER_SRC), str(FACTORY_SRC)):
    if _entry not in sys.path:
        sys.path.insert(0, _entry)

from nulloracle import KEY_REF_ENV, SIDECAR_PATH_ENV, SERVICE_ACCOUNT_ENV  # noqa: E402

#: A fixed 32-byte key, so "the same key opened it" is an assertion about
#: the bytes used twice rather than about a value the test happened to hold.
TEST_KEY_HEX = "0f" * 32


@pytest.fixture(autouse=True)
def _no_ambient_sidecar_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    """Clear every variable this member reads before each test.

    Autouse and unconditional: the default state of a test is the state a
    deployment has before anyone configures it, so the tests that assert on
    *unconfigured* behaviour do not have to fight a fixture that helpfully
    configured something behind their back.
    """
    for name in (KEY_REF_ENV, SIDECAR_PATH_ENV, SERVICE_ACCOUNT_ENV):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def sidecar_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Configure the sidecar at a path under this test's temporary directory."""
    path = tmp_path / "z0" / "null" / "sidecar.enc"
    monkeypatch.setenv(SIDECAR_PATH_ENV, str(path))
    return path


@pytest.fixture
def key_ref(monkeypatch: pytest.MonkeyPatch) -> str:
    """Configure a ``hex:`` key reference for this test."""
    reference = f"hex:{TEST_KEY_HEX}"
    monkeypatch.setenv(KEY_REF_ENV, reference)
    return reference


@pytest.fixture
def node_id() -> str:
    """A fresh canonical node UUID, the key §7.1's schema is keyed by."""
    return str(uuid.uuid4())


@pytest.fixture
def raised_named():
    """Assert that a block raised an error of a given class *name*.

    The composed sidecar is imported by the factory's scan under a synthetic
    module alias, so the exception it raises is structurally — but not
    identically — the one a direct ``import nulloracle`` yields, and
    ``pytest.raises(<canonical class>)`` does not match it.  This is the same
    wrinkle ``tests/feature-store/test_registration.py`` documents for
    ``isinstance`` across the two module worlds, and the same answer: assert
    on the name, which the two copies agree on because they are the same
    source.

    Deliberately not a blanket ``except Exception``: the name is compared, so
    a test still fails when the wrong error comes out — it merely stops
    caring which of two identical classes raised it.
    """

    def _matched(name: str):
        import contextlib

        @contextlib.contextmanager
        def _ctx():
            try:
                yield
            except Exception as exc:  # noqa: BLE001 - the name is the assertion
                assert type(exc).__name__ == name, (
                    f"expected {name}, got {type(exc).__name__}: {exc}"
                )
                return
            raise AssertionError(f"expected {name} to be raised; nothing was")

        return _ctx()

    return _matched


@pytest.fixture
def node_ids() -> "callable":
    """A factory for ``n`` distinct canonical node UUIDs."""

    def _make(count: int) -> list[str]:
        return [str(uuid.uuid4()) for _ in range(count)]

    return _make
